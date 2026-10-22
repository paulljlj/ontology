"""Explainable, time-bounded service diagnostics. No evaluation data is read."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from statistics import mean
from math import isfinite
from .data import instant, load_case
from .graph import MCPGraph


def number(row: dict, field: str) -> float | None:
    try:
        value = float(row[field]) if row.get(field, '') != '' else None
        return value if value is not None and isfinite(value) else None
    except (ValueError, TypeError):
        return None


def evidence(row: dict, field: str, unit: str, object_id: str, source: str) -> dict:
    return {'source': source, 'record_id': row.get('sample_id') or row.get('event_id') or
            '|'.join(str(row.get(k, '')) for k in ('case_id','timestamp','service_id','route_id')),
            'case_id': row.get('case_id'), 'route_id': row.get('route_id'),
            'object_id': object_id, 'field': field,
            'value': row.get(field), 'unit': unit,
            'timestamp': row.get('timestamp') or row.get('event_start'),
            'available_at': row.get('available_at')}


def runs(series: list[dict], threshold, minutes: int) -> list[list[dict]]:
    """Return contiguous minute-sampled runs; missing values break a run."""
    groups, current = [], []
    for row in sorted(series, key=lambda r: r['timestamp']):
        if current and (instant(row['timestamp']) - instant(current[-1]['timestamp'])).total_seconds() != minutes * 60:
            groups.append(current)
            current = []
        if row['drop_pp'] is not None and threshold(row['drop_pp']):
            current.append(row)
        else:
            if current:
                groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def service_status(tables: dict, case: dict, rules: dict, cutoff=None) -> list[dict]:
    opts = rules['availability']
    major = opts['major_alert']
    watch = opts['watch']
    by_service = defaultdict(list)
    for row in tables['service_metrics']:
        by_service[row['service_id']].append(row)
    result = []
    baseline_start, baseline_end = instant(case['baseline_start']), instant(case['baseline_end_exclusive'])
    analysis_start, analysis_end = instant(case['analysis_start']), instant(case['analysis_end_exclusive'])
    expected_end = min(analysis_end, cutoff) if cutoff is not None else analysis_end
    expected_minutes = max(0, int((expected_end-analysis_start).total_seconds() / int(case['sampling_seconds'])))
    for sid in sorted(s['service_id'] for s in tables['services']):
        rows = by_service[sid]
        base = [number(r,'availability_pct') for r in rows if baseline_start <= instant(r['timestamp']) < baseline_end
                and r['measurement_status'] == 'observed' and number(r,'availability_pct') is not None]
        base_avg = mean(base) if base else None
        window = []
        for row in rows:
            if not analysis_start <= instant(row['timestamp']) < analysis_end:
                continue
            item = dict(row)
            availability = number(item, 'availability_pct') if item['measurement_status'] == 'observed' else None
            item['drop_pp'] = round(base_avg - availability, 5) if base_avg is not None and availability is not None else None
            window.append(item)
        # Absent rows are unknown observations, never zero-availability or healthy.
        major_runs = runs(window, lambda x: x > major['drop_pp_strictly_greater_than'], 1)
        watch_runs = runs(window, lambda x: watch['drop_pp_at_least'] <= x <= watch['drop_pp_at_most'], 1)
        valid = [r for r in window if r['drop_pp'] is not None]
        peak = max(valid, key=lambda r:r['drop_pp']) if valid else None
        qualifying = [r for r in major_runs if len(r) >= major['consecutive_valid_samples']]
        watch_qualifying = [r for r in watch_runs if len(r) >= watch['consecutive_valid_samples']]
        cls = 'unobserved' if not valid else ('major' if qualifying else ('watch_pending_support' if watch_qualifying else
                   ('trend_observing' if peak and peak['drop_pp'] >= watch['drop_pp_at_least'] else 'normal')))
        selected_runs = qualifying or watch_qualifying or major_runs or watch_runs
        best = max(selected_runs, key=len) if selected_runs else []
        result.append({'service_id':sid, 'classification':cls,
            'baseline_availability_pct':round(base_avg, 4) if base_avg is not None else None,
            'analysis_mean_availability_pct':round(mean(number(r,'availability_pct') for r in valid),4) if valid else None,
            'mean_drop_pp':round(mean(r['drop_pp'] for r in valid),4) if valid else None,
            'peak_drop_pp':peak['drop_pp'] if peak else None,
            'peak_sample':evidence(peak,'availability_pct','percent',sid,'service_metrics') if peak else None,
            'first_decline_at':best[0]['timestamp'] if best else None,
            'last_decline_sample_at':best[-1]['timestamp'] if best else None,
            'longest_contiguous_minutes':len(best), 'valid_minutes':len(valid),
            'missing_minutes':max(0,expected_minutes-len(valid)), 'major_intervals':[
                {'from':r[0]['timestamp'], 'through_sample':r[-1]['timestamp'],'minutes':len(r)} for r in qualifying],
            'sample_routes':{r['timestamp']:r['route_id'] for r in window},
            'example_sample':evidence(best[0],'availability_pct','percent',sid,'service_metrics') if best else None})
    return result


def _resource_metrics(tables:dict, typ:str, rid:str, case:dict) -> tuple[list[dict],list[dict]]:
    table, id_key = ('node_metrics','node_id') if typ == 'node' else ('link_metrics','link_id')
    all_rows = [r for r in tables[table] if r[id_key] == rid]
    baseline = [r for r in all_rows if instant(case['baseline_start']) <= instant(r['timestamp']) < instant(case['baseline_end_exclusive'])
                and r['measurement_status'] == 'observed']
    window = [r for r in all_rows if instant(case['analysis_start']) <= instant(r['timestamp']) < instant(case['analysis_end_exclusive'])]
    return baseline, window


def _peak(rows:list[dict], field:str, reverse:bool = False) -> dict | None:
    valid = [r for r in rows if r['measurement_status'] == 'observed' and number(r,field) is not None]
    return (min(valid, key=lambda r:number(r,field)) if reverse else max(valid,key=lambda r:number(r,field))) if valid else None


def resource_signals(tables:dict, case:dict, kind:str, rid:str) -> dict:
    baseline, rows = _resource_metrics(tables,kind,rid,case)
    tab = 'node_metrics' if kind == 'node' else 'link_metrics'
    signals, contrary, missing, context = [], [], [], []
    observed = [r for r in rows if r['measurement_status']=='observed']
    if rows and len(observed) < len(rows):
        missing.append(f'{rid}观测缺失 {len(rows)-len(observed)}/{len(rows)} 分钟')
    if not rows:
        missing.append(f'{rid}分析窗口无遥测')
    for r in [x for x in tables['events'] if x['object_id']==rid and x['event_kind'] in ('alarm','event','data_quality','planned_change')
              and instant(x['event_start']) < instant(case['analysis_end_exclusive'])]:
        if r['event_kind'] == 'data_quality':
            missing.append('数据质量事件 '+r['event_id']+'：'+r['event_code'])
        elif r['event_kind'] == 'planned_change':
            contrary.append(evidence(r,'event_code','code',rid,'events'))
        else:
            signals.append(evidence(r,'event_code','code',rid,'events'))
    p = _peak(rows,'demand_utilization_pct')
    if p:
        item=evidence(p,'demand_utilization_pct','percent',rid,tab)
        if number(p,'demand_utilization_pct') >= 85:
            signals.append(item)
        else:
            contrary.append(item)
    p = _peak(rows,'discarded_mbps')
    if p and number(p,'discarded_mbps') > .1:
        signals.append(evidence(p,'discarded_mbps','Mbps',rid,tab))
    if kind == 'node':
        for field, floor, unit in [('queue_depth_mb',1,'MB'),('seu_events_per_min',0,'events/min'),
                                   ('ecc_corrected_events_per_min',0,'events/min'),('reset_events_per_min',0,'events/min')]:
            p = _peak(rows,field)
            if p and number(p,field)>floor:
                signals.append(evidence(p,field,unit,rid,tab))
        p = _peak(rows,'bus_voltage_v',reverse=True)
        base = [number(r,'bus_voltage_v') for r in baseline if number(r,'bus_voltage_v') is not None]
        if p and base and number(p,'bus_voltage_v') < mean(base)-2:
            signals.append(evidence(p,'bus_voltage_v','V',rid,tab))
        # Environment proxy alone must not be interpreted as equipment failure.
        p = _peak(rows,'radiation_proxy_counts_per_min')
        if p and number(p,'radiation_proxy_counts_per_min') >= 100:
            context.append(evidence(p,'radiation_proxy_counts_per_min','synthetic counts/min',rid,tab))
    else:
        p = _peak(rows,'snr_db',reverse=True)
        base = [number(r,'snr_db') for r in baseline if number(r,'snr_db') is not None]
        if p and base and number(p,'snr_db') < mean(base)-5:
            signals.append(evidence(p,'snr_db','dB',rid,tab))
        p = _peak(rows,'bit_error_rate')
        if p and number(p,'bit_error_rate') >= 1e-4:
            signals.append(evidence(p,'bit_error_rate','ratio',rid,tab))
        p = next((r for r in rows if r['operational_state']=='DOWN'),None)
        if p:
            signals.append(evidence(p,'operational_state','state',rid,tab))
    equipment = any(e.get('field') in ('reset_events_per_min','ecc_corrected_events_per_min','seu_events_per_min','bus_voltage_v','snr_db','bit_error_rate','operational_state')
                    or e.get('value') in ('POWER_BUS_LOW','LOW_SNR','PROCESSOR_RESET','MEMORY_ERROR_COUNT_HIGH') for e in signals)
    overload = any(e.get('field') in ('discarded_mbps','queue_depth_mb') or
                   (e.get('field') == 'demand_utilization_pct' and float(e['value']) > 100) for e in signals)
    if equipment:
        mechanism = '设备或链路质量劣化，与受影响路径的时序需进一步核实'
    elif overload:
        mechanism = '资源到达负载、丢弃或队列积压，可能导致路径交付下降'
    elif any(e['field']=='demand_utilization_pct' for e in signals):
        mechanism = '资源负载偏高，但尚不能单独解释服务下降'
    else:
        mechanism = '共享路径关联，缺少独立资源故障证据'
    return {'support':signals,'contrary':contrary,'missing':missing,'context':context,'mechanism':mechanism,
            'has_support':equipment or overload or any(e['field']=='demand_utilization_pct' for e in signals)}


def analyze_case(dataset_dir, case_id: str, cutoff: str | None = None, graph=None,
                 observation_at: str | None = None) -> dict:
    """Produce report dict. Production requires MCPGraph; LocalGraph is explicit test/dev only."""
    case_data = load_case(dataset_dir,case_id,cutoff,observation_at)
    tables, case, rules = case_data['tables'],case_data['case'],case_data['rules']
    graph = graph if graph is not None else MCPGraph(__import__('os').environ.get('NEO4J_MCP_BIN','neo4j-mcp'))
    backend = 'mcp' if graph.__class__.__name__ == 'MCPGraph' else 'local_test_only'
    statuses = service_status(tables,case,rules,case_data['cutoff'])
    # Query the temporal graph at the first sample and at every route-version change.
    timestamps={case['analysis_start']}
    timestamps.update(r['effective_from'] for r in tables['routes'] if
                      instant(case['analysis_start']) < instant(r['effective_from']) < instant(case['analysis_end_exclusive'])
                      and instant(r['effective_from']) <= case_data['cutoff'])
    snapshots = graph.exposures_many(case_id, sorted(timestamps)) if hasattr(graph, 'exposures_many') else {t:graph.exposures(case_id,t) for t in sorted(timestamps)}
    if any(not v for v in snapshots.values()):
        raise RuntimeError('empty temporal graph exposures; import graph before diagnosis')
    exposures = {}
    graph_mismatches=[]
    for status in statuses:
        sid=status['service_id']
        for ts, route_id in status['sample_routes'].items():
            graph_at=max((t for t in snapshots if instant(t)<=instant(ts)), key=instant)
            matched=[r for r in snapshots[graph_at] if r['service_id']==sid and r['route_id']==route_id]
            if len(matched)!=1:
                graph_mismatches.append(f'{sid}@{ts}: metric route {route_id} not in MCP graph')
            else:
                exposures[(sid,ts)]=matched[0]
        status.pop('sample_routes')
    if graph_mismatches:
        raise RuntimeError('route graph/observation inconsistent: '+ '; '.join(graph_mismatches[:3]))
    services_by_id={s['service_id']:s for s in tables['services']}
    major=[s for s in statuses if s['classification']=='major']
    affected={s['service_id'] for s in major}
    planned={e['event_id']:e for e in tables['events'] if e['event_kind']=='planned_change'}
    for status in statuses:
        if status['classification']=='trend_observing' and status['first_decline_at']:
            sample_route=next((r for r in tables['service_metrics'] if r['service_id']==status['service_id']
                              and r['timestamp']==status['first_decline_at']),None)
            route=next((r for r in tables['routes'] if sample_route and r['route_id']==sample_route['route_id']),None)
            event=planned.get(route.get('change_record_id')) if route else None
            if event and (not event['planned_end'] or instant(status['last_decline_sample_at']) < instant(event['planned_end'])):
                status['classification']='planned_transition'
                status['planned_change_evidence']=evidence(event,'event_code','code',event['object_id'],'events')
    from .context import diagnostic_context, service_observation, build_context
    phases = diagnostic_context(tables, case, case_data['cutoff'], snapshots, statuses)
    phase_cap = {(c['object_type'],c['object_id']):c for c in phases['capacity']['resources']}
    phase_env = {e['object_id']:e for e in phases['environment']['objects']}
    phase_paths = {p['relay_id']:p for p in phases['path_controls']}
    # Verified healthy controls require observed, route-matched data at the exposure time.
    control_context = build_context(tables, case, case_data['cutoff'], snapshots, statuses)
    normal_ids = {s['service_id'] for s in statuses if s['classification']=='normal'}
    candidate_services = major + [s for s in statuses if s['classification']=='watch_pending_support']
    if not candidate_services:
        candidate_services = [s for s in statuses if s['classification']=='trend_observing']
    involved=defaultdict(set)
    involved_times=defaultdict(set)
    exposed=defaultdict(set)
    first_ts=case['analysis_start']
    for s in candidate_services:
        # A switched service must be correlated against the route at the decline,
        # not the route that happened to be active at analysis-window start.
        evidence_ts = s['first_decline_at'] or first_ts
        ex=exposures.get((s['service_id'],evidence_ts))
        if ex:
            for k in ('nodes','links'):
                for rid in ex[k]:
                    resource=(k[:-1],rid)
                    involved[resource].add(s['service_id'])
                    involved_times[resource].add(evidence_ts)
    # Controls share the resource at the SAME sample time as a candidate exposure.
    for resource, times in involved_times.items():
        k, rid = resource
        for s in statuses:
            for ts in times:
                ex=exposures.get((s['service_id'],ts))
                if ex and rid in ex[k+'s']:
                    exposed[resource].add(s['service_id'])
                    break
    candidates=[]
    for (kind,rid), sids in involved.items():
        if len(sids)<2 and len(candidate_services)>1:
            continue
        info=resource_signals(tables,case,kind,rid)
        # An alert alone is not enough if no observed resource metric or service degradation.
        example=next((s for s in candidate_services if s['service_id'] in sids and s['peak_sample']),None)
        support=list(info['support'])
        if example:
            support.insert(0,example['peak_sample'])
        healthy=[sid for sid in exposed[(kind,rid)]-sids if sid in normal_ids and
                 any(service_observation(control_context,sid,ts)['state']=='normal_sample'
                     and rid in control_context['membership'].get((sid,instant(ts)),{}).get(kind+'s',[])
                     for ts in involved_times[(kind,rid)])]
        cap = phase_cap.get((kind,rid))
        env = phase_env.get(rid) if kind == 'node' else None
        path = phase_paths.get(rid) if kind == 'node' else None
        mechanism = info['mechanism']
        synchronized = []
        if cap:
            sample = cap['representative_sample']
            if sample:
                synchronized = sample['evidence'] + [o['evidence'] for o in sample['service_observations']
                                                     if o['state']=='declining'][:2]
            if cap['assessment']=='overload_with_service_decline':
                mechanism = '同分钟到达流量超过有效容量并伴随业务下降，支持过载候选；需核实队列和逐业务损失'
                if sample and sample['change_driver']=='capacity_reduction':
                    mechanism += '；相对基线主要表现为有效容量下降，未见该资源到达量同幅增长，源端需求仍需单独核对'
            elif cap['assessment']=='loss_without_total_overload':
                mechanism = '存在丢弃但实测总到达量未超有效容量；优先核查设备、链路质量或局部队列，不判为总容量过载'
            elif cap['assessment']=='unknown':
                mechanism = '容量或到达流量缺测，不能确认或排除过载；共享路径关联仍待补证据'
            if path and path['assessment']=='path_selective_decline_without_observed_relay_overload':
                mechanism = path['interpretation']
        if env and env['assessment']=='proxy_device_service_cooccurrence':
            if env['timeline']['temporal_relation']=='proxy_after_first_observed_decline':
                mechanism += '；环境代理升高晚于首次业务下降，不支持作为起始根因'
                info['contrary'] += env['timeline']['first_service_decline']['evidence'][:2]
            else:
                mechanism += '；环境代理与设备错误、业务下降同分钟共现，环境相关设备异常待验证'
            sample = env['representative_sample']
            synchronized += [sample['proxy']] + sample['device_responses']
        if cap and cap['assessment']=='within_capacity_in_observed_samples':
            # Adequate measured total capacity is evidence AGAINST total overload,
            # not independent support for blaming the shared resource.
            info['contrary'] += (cap['representative_sample'] or {}).get('evidence', [])
            support = [e for e in synchronized if e['field'] in
                       ('radiation_proxy_counts_per_min','seu_events_per_min','ecc_corrected_events_per_min','reset_events_per_min')] + support
        else:
            support = synchronized + support
        missing = list(info['missing'])
        if cap and cap['valid_samples'] < cap['expected_samples']:
            missing += cap['missing_evidence'][:1]
        candidates.append({'object_type':kind,'object_id':rid,
            'affected_service_ids':sorted(sids),'all_exposed_service_ids':sorted(exposed[(kind,rid)]),
            'unaffected_exposed_service_ids':sorted(healthy),'hypothesis':mechanism,
            'environmental_context':info['context'],
            'diagnostic_assessments':{'environment':env['assessment'] if env else None,
                'capacity':cap['assessment'] if cap else None,'path_controls':path['assessment'] if path else None},
            'supporting_evidence':support,'counter_evidence':info['contrary'],
            'missing_evidence':missing,
            'evidence_strength':'multi_signal' if info['has_support'] and len(support)>=3 and not missing else 'limited',
            '_rank':(len(sids & affected),int(info['has_support']),len(sids),-len(healthy))})
    candidates.sort(key=lambda c:c['_rank'],reverse=True)
    for c in candidates:
        del c['_rank']
    watch=[]
    for s in statuses:
        if s['classification']!='watch_pending_support':
            continue
        sid=s['service_id']
        supportive=[c for c in candidates if sid in c['affected_service_ids'] and any(
             e['field']=='demand_utilization_pct' and float(e['value'])>=85 or
             e['field'] in ('seu_events_per_min','ecc_corrected_events_per_min','reset_events_per_min')
             for e in c['supporting_evidence'] if e.get('value') not in (None,''))]
        if supportive:
            s['classification']='watch'
            watch.append({'service_id':sid,'service':s,'supporting_resource':supportive[0]['object_id'],
                          'supporting_evidence':supportive[0]['supporting_evidence'][:3]})
        else:
            s['classification']='trend_observing'
    normal=[s for s in statuses if s['classification']=='normal']
    controls=[]
    for c in candidates[:5]:
        same_destination=[s['service_id'] for s in normal
             if services_by_id[s['service_id']]['destination_ground_station_id'] in
              {services_by_id[i]['destination_ground_station_id'] for i in c['affected_service_ids']}
             and s['service_id'] not in c['all_exposed_service_ids']]
        controls.append({'candidate_id':c['object_id'],'same_resource_normal':c['unaffected_exposed_service_ids'],
                         'same_destination_other_path_normal':same_destination[:10],
                         'comparison_note':'同资源正常业务是反例；同地面站不同路径业务帮助区分站点与中继问题'})
    quality={'unobserved_service_ids':[s['service_id'] for s in statuses if s['classification']=='unobserved'],
             'baseline_missing_services':[s['service_id'] for s in statuses if s['baseline_availability_pct'] is None],
             'service_missing_minutes':sum(s['missing_minutes'] for s in statuses),
             'telemetry_gaps':[{'object_id':c['object_id'],'details':c['missing_evidence']} for c in candidates if c['missing_evidence']]}
    summary=({'priority_object':candidates[0]['object_id'], 'assessment':'优先核查，共同依赖和独立遥测仅支持待验证假设',
              'basis':candidates[0]['supporting_evidence'][:3],
              'next_evidence':['核对资源原始遥测及同一时段容量配置','比对变更计划和业务端探测记录'] +
                              candidates[0]['missing_evidence']} if candidates and affected else
             {'priority_object':None,'assessment':'未确认持续重大异常；继续观察轻微下降和遥测缺口',
              'basis':[s['peak_sample'] for s in statuses if s['peak_sample'] and s['peak_drop_pp']>=1][:3],
              'next_evidence':['延长观察窗口确认持续性','核对路径资源遥测及计划切换']})
    quality['capacity_completeness'] = [
        {'object_id':c['object_id'], 'object_type':c['object_type'],
         'valid_samples':c['valid_samples'], 'expected_samples':c['expected_samples']}
        for c in phases['capacity']['resources'] if c['valid_samples'] < c['expected_samples']]
    quality['environment_scope_limitations'] = phases['environment']['scope_note']
    summary['environment_findings'] = [
        {'object_id':e['object_id'],'assessment':e['assessment'],'basis':e['peak_proxy_evidence']}
        for e in phases['environment']['objects'] if e['elevated_sample_count']]
    summary['same_relay_path_findings'] = [
        {'relay_id':p['relay_id'],'assessment':p['assessment'],
         'different_path_control_sample_count':p['different_path_control_sample_count']}
        for p in phases['path_controls'] if p['comparisons']]
    summary['diagnostic_order'] = phases['analysis_order']
    if summary['priority_object']:
        top = candidates[0]
        summary['assessment'] = top['hypothesis']
        summary['diagnostic_assessments'] = top['diagnostic_assessments']
        summary['basis'] = top['supporting_evidence'][:8]
        summary['next_evidence'] += ['核查外部环境实测与设备错误的先后，环境代理共现不代表已证明因果',
                                     '补充逐业务/出端口队列、QoS优先级，解释同星业务选择性受损']
    observation_end = (instant(observation_at) + timedelta(
        seconds=int(case['sampling_seconds']))) if observation_at else instant(case['analysis_end_exclusive'])
    return {'schema_version':'1.1' ,'dataset_id':'satellite_demo_v1','case_id':case_id,
            'graph_backend':backend,'as_of':case_data['cutoff'].isoformat(),
            'analysis_window':{'from':case['analysis_start'],
                               'to_exclusive':min(instant(case['analysis_end_exclusive']),case_data['cutoff'],observation_end).isoformat()},
            'diagnostic_policy':{
                'availability_object':rules['availability']['object'],
                'availability_formula':rules['availability']['formula'],
                'baseline':rules['availability']['baseline'],
                'drop_unit':rules['availability']['drop_unit'],
                'major_alert':rules['availability']['major_alert'],
                'watch':rules['availability']['watch'],
                'policy_note':'演示阈值，可配置，不是行业标准'},
            'anomaly_overview':{'major_count':len(major),'services':major,'all_service_statuses':statuses},
            'root_cause_candidates':candidates[:12],
            'minor_anomalies':{'watch':watch,'observing':[s for s in statuses if s['classification'] in ('trend_observing','planned_transition')]},
            'impact_and_controls':{'affected_service_ids':sorted(affected),'healthy_service_ids':[s['service_id'] for s in normal],
                                   'candidate_controls':controls},
            'conclusion_and_missing_evidence':summary,'data_quality':quality,
            'diagnostic_process':phases}
