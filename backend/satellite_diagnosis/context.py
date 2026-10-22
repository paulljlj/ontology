"""Synchronized environment -> capacity -> path-control checks on filtered inputs.

Thresholds here are explicit demonstration heuristics, not space-weather models.
Call through analyze_case to enforce manifest and availability-time isolation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from statistics import mean
from .data import instant
from .diagnosis import evidence, number

RULES = {
    'rule_id': 'diagnostic_context_demo_v1',
    'source': 'satellite_diagnosis/context.py',
    'radiation_proxy_at_least': 100,
    'service_drop_pp_at_least': 1,
    'baseline_relative_change_pct': 5,
    'overload_definition': 'observed ingress_mbps > observed effective_capacity_mbps',
    'scope': 'synthetic demonstration only; no calibrated environmental or causal model',
}
ERROR_FIELDS = ('seu_events_per_min', 'ecc_corrected_events_per_min', 'reset_events_per_min')


def observed(row, field):
    value = number(row, field) if row and row.get('measurement_status') == 'observed' else None
    return value if value is not None and (value >= 0 or field in ('snr_db', 'temperature_c')) else None


def aggregate(rows, field, source, object_id):
    valid = [r for r in rows if observed(r, field) is not None]
    return {'source': source, 'object_id': object_id, 'field': field, 'aggregation': 'mean',
            'value': round(mean(observed(r, field) for r in valid), 6) if valid else None,
            'sample_count': len(valid), 'record_ids': [r['sample_id'] for r in valid],
            'from': min((r['timestamp'] for r in valid), default=None),
            'last_sample_at': max((r['timestamp'] for r in valid), default=None)}


def _unique_index(rows, keys):
    result = {}
    for row in rows:
        key = tuple(row[k] for k in keys)
        if key in result:
            raise ValueError('duplicate synchronized observation: ' + str(key))
        result[key] = row
    return result


def build_context(tables, case, cutoff, snapshots, statuses):
    """Prepare same-time graph/metric joins, independent of service missingness."""
    end = min(cutoff, instant(case['analysis_end_exclusive']))
    step = timedelta(seconds=int(case['sampling_seconds']))
    times, moment = [], instant(case['analysis_start'])
    while moment + step <= end:
        times.append(moment.isoformat(timespec='milliseconds'))
        moment += step
    # Normalize to datetimes for joins; do not compare ISO offsets lexically.
    graph_at = {instant(t): rows for t, rows in snapshots.items()}
    membership = {}
    for ts in times:
        eligible = [t for t in graph_at if t <= instant(ts)]
        if not eligible:
            raise ValueError('no graph snapshot at ' + ts)
        for ex in graph_at[max(eligible)]:
            key = (ex['service_id'], instant(ts))
            if key in membership:
                raise ValueError('ambiguous active graph route: ' + str(key))
            membership[key] = ex
    indexed = {}
    for table, key in [('node_metrics', 'node_id'), ('link_metrics', 'link_id'),
                       ('service_metrics', 'service_id'), ('traffic', 'service_id')]:
        rows = [dict(r, timestamp_key=instant(r['timestamp'])) for r in tables[table]]
        indexed[table] = _unique_index(rows, (key, 'timestamp_key'))
    hops = defaultdict(list)
    for h in tables['route_hops']:
        hops[h['route_id']].append(h)
    relays, links = set(), set()
    for ex in membership.values():
        links.update(ex['links'])
        for h in hops[ex['route_id']]:
            if int(h['hop_index']) > 0 and h['outgoing_link_id'] and h['node_id'] in ex['nodes']:
                relays.add(h['node_id'])
    context = {'times': times, 'membership': membership, 'indexed': indexed,
               'statuses': {s['service_id']: s for s in statuses},
               'relays': sorted(relays), 'links': sorted(links), 'hops': hops}
    return context


def service_observation(ctx, sid, ts):
    row = ctx['indexed']['service_metrics'].get((sid, instant(ts)))
    ex = ctx['membership'].get((sid, instant(ts)))
    base = ctx['statuses'].get(sid, {}).get('baseline_availability_pct')
    val = observed(row, 'availability_pct')
    valid = val is not None and base is not None and ex and row['route_id'] == ex['route_id']
    drop = round(base-val, 5) if valid else None
    return {'service_id': sid, 'state': ('unknown' if drop is None else
            'declining' if drop >= RULES['service_drop_pp_at_least'] else 'normal_sample'),
            'drop_pp': drop, 'baseline_availability_pct': base,
            'route_id': ex['route_id'] if ex else None,
            'evidence': evidence(row, 'availability_pct', 'percent', sid, 'service_metrics') if valid else None}


def _exposed(ctx, kind, rid, ts):
    return sorted(sid for (sid, t), ex in ctx['membership'].items()
                  if t == instant(ts) and rid in ex['nodes' if kind == 'node' else 'links'])


def assess_environment(tables, case, ctx):
    """Environment proxy is context, never automatic fault proof or counter-evidence."""
    results = []
    for node in tables['nodes']:
        rid = node['node_id']
        samples = []
        valid_proxy = 0
        first_device_response, first_service_decline = None, None
        for ts in ctx['times']:
            row = ctx['indexed']['node_metrics'].get((rid, instant(ts)))
            if first_device_response is None and any(observed(row, f) is not None and observed(row, f)>0 for f in ERROR_FIELDS):
                first_device_response = {'timestamp': ts, 'evidence': [evidence(row,f,'events/min',rid,'node_metrics')
                                         for f in ERROR_FIELDS if observed(row,f) is not None and observed(row,f)>0]}
            if first_service_decline is None:
                decline = [service_observation(ctx,sid,ts) for sid in _exposed(ctx,'node',rid,ts)]
                decline = [d for d in decline if d['state']=='declining']
                if decline:
                    first_service_decline = {'timestamp':ts, 'evidence':[d['evidence'] for d in decline]}
            proxy = observed(row, 'radiation_proxy_counts_per_min')
            if proxy is not None:
                valid_proxy += 1
            if proxy is None or proxy < RULES['radiation_proxy_at_least']:
                continue
            responses = [evidence(row, f, 'events/min', rid, 'node_metrics')
                         for f in ERROR_FIELDS if observed(row, f) is not None]
            service = [service_observation(ctx, sid, ts) for sid in _exposed(ctx, 'node', rid, ts)]
            samples.append({'timestamp': ts, 'proxy': evidence(row, 'radiation_proxy_counts_per_min',
                            'synthetic counts/min', rid, 'node_metrics'), 'device_responses': responses,
                            'positive_device_response': any(observed(row, f) is not None and observed(row, f) > 0
                                                            for f in ERROR_FIELDS),
                            'service_observations': service})
        if not samples and rid not in ctx['relays']:
            continue
        joint = [s for s in samples if s['positive_device_response'] and
                 any(x['state'] == 'declining' for x in s['service_observations'])]
        response = any(s['positive_device_response'] for s in samples)
        state = ('proxy_device_service_cooccurrence' if joint else
                 'proxy_with_device_response' if response else
                 'proxy_elevated_without_observed_device_response' if samples else
                 'proxy_not_elevated_in_observed_samples' if valid_proxy else 'unknown')
        baseline = [r for r in tables['node_metrics'] if r['node_id'] == rid and
                    instant(case['baseline_start']) <= instant(r['timestamp']) < instant(case['baseline_end_exclusive'])]
        representative = joint[0] if joint else samples[0] if samples else None
        normal_rows = [ctx['indexed']['node_metrics'].get((rid, instant(ts))) for ts in ctx['times']]
        normal_rows = [r for r in normal_rows if observed(r, 'radiation_proxy_counts_per_min') is not None]
        peak = max(normal_rows, key=lambda r: observed(r, 'radiation_proxy_counts_per_min')) if normal_rows else None
        if state == 'unknown':
            interpretation = '环境代理缺测，不能确认或排除环境异常。'
        elif state == 'proxy_not_elevated_in_observed_samples':
            interpretation = '已观测样本的辐射代理未达到演示阈值；不能据此排除未采集的天气、干扰或其他环境影响。'
        elif joint:
            interpretation = '环境代理、设备错误与业务下降在同一分钟共现，支持优先核查环境相关设备异常；分钟采样不能确认先后或证明辐射导致故障。'
        else:
            interpretation = '环境代理指标单独升高不足以解释业务故障；未观测到响应不等于排除环境影响。'
        onset_lag = ((instant(first_service_decline['timestamp'])-instant(samples[0]['timestamp'])).total_seconds()
                     if samples and first_service_decline else None)
        temporal_relation = ('unknown' if onset_lag is None else 'proxy_after_first_observed_decline' if onset_lag < 0
                             else 'same_minute_onset' if onset_lag == 0 else 'proxy_precedes_first_observed_decline')
        if onset_lag is not None and onset_lag < 0:
            interpretation += ' 已观测到的代理升高晚于首次业务下降，不支持其作为起始根因；需检查更早观测是否缺失。'
        results.append({'object_id': rid, 'assessment': state,
                        'proxy_valid_samples': valid_proxy, 'expected_samples': len(ctx['times']),
                        'elevated_sample_count': len(samples),
                        'first_elevated_at': samples[0]['timestamp'] if samples else None,
                        'first_joint_observation_at': joint[0]['timestamp'] if joint else None,
                        'causal_status':'not_established',
                        'timeline': {'temporal_relation':temporal_relation, 'first_device_response':first_device_response,
                                     'first_service_decline':first_service_decline,
                                     'proxy_to_first_service_decline_seconds':
                                        onset_lag,
                                     'note':'仅为窗口内首次观测时间差；0表示同分钟，不代表环境先于故障。缺测会影响首次时间。'},
                        'baseline_proxy': aggregate(baseline, 'radiation_proxy_counts_per_min', 'node_metrics', rid),
                        'peak_proxy_evidence': evidence(peak, 'radiation_proxy_counts_per_min', 'synthetic counts/min',
                                                        rid, 'node_metrics') if peak else None,
                        'elevated_samples': samples, 'representative_sample': representative,
                        'interpretation': interpretation,
                        'missing_evidence': ['真实空间环境/辐射剂量、姿态与遮挡、地面天气及射频干扰观测未提供',
                                             '需更高时间分辨率的设备错误日志验证先后与机制']})
    return {'order': 1, 'rules': RULES, 'objects': results,
            'scope_note': '先检查外部环境，但数据仅提供合成辐射代理；SNR/BER属于链路响应，不能据此识别天气或干扰源。'}


def assess_capacity(tables, case, ctx, kind, rid):
    """Use measured ingress/capacity, not source offered load, to test overload."""
    table = 'node_metrics' if kind == 'node' else 'link_metrics'
    id_field = 'node_id' if kind == 'node' else 'link_id'
    forwarded = 'forwarded_mbps' if kind == 'node' else 'transmitted_mbps'
    base = [r for r in tables[table] if r[id_field] == rid and
            instant(case['baseline_start']) <= instant(r['timestamp']) < instant(case['baseline_end_exclusive'])]
    baseline = {f: aggregate(base, f, table, rid) for f in ('ingress_mbps', 'effective_capacity_mbps')}
    static = next((r for r in tables['nodes' if kind == 'node' else 'links'] if r[id_field] == rid), {})
    nominal_field = 'forwarding_capacity_mbps' if kind == 'node' else 'nominal_capacity_mbps'
    samples = []
    for ts in ctx['times']:
        row = ctx['indexed'][table].get((rid, instant(ts)))
        cap, ingress = observed(row, 'effective_capacity_mbps'), observed(row, 'ingress_mbps')
        valid = cap is not None and ingress is not None
        breached = ingress > cap if valid else None
        fields = ('effective_capacity_mbps', 'ingress_mbps', forwarded, 'discarded_mbps', 'demand_utilization_pct')
        ev = [evidence(row, f, 'percent' if f.endswith('_pct') else 'Mbps', rid, table)
              for f in fields if observed(row, f) is not None]
        expected = _exposed(ctx, kind, rid, ts)
        contributions, missing = [], []
        for sid in expected:
            ex = ctx['membership'][(sid, instant(ts))]
            traffic = ctx['indexed']['traffic'].get((sid, instant(ts)))
            value = observed(traffic, 'offered_mbps')
            if value is None or traffic['route_id'] != ex['route_id']:
                missing.append(sid)
            else:
                contributions.append(evidence(traffic, 'offered_mbps', 'Mbps', sid, 'traffic'))
        offered = sum(float(e['value']) for e in contributions) if expected and not missing else None
        service = [service_observation(ctx, sid, ts) for sid in expected]
        bload, bcap = baseline['ingress_mbps']['value'], baseline['effective_capacity_mbps']['value']
        load_change = (ingress/bload-1)*100 if ingress is not None and bload is not None and bload > 0 else None
        capacity_change = (cap/bcap-1)*100 if cap is not None and bcap is not None and bcap > 0 else None
        growing = load_change is not None and load_change > RULES['baseline_relative_change_pct']
        shrinking = capacity_change is not None and capacity_change < -RULES['baseline_relative_change_pct']
        driver = ('demand_growth_and_capacity_reduction' if growing and shrinking else
                  'capacity_reduction' if shrinking else 'demand_growth' if growing else
                  'no_large_baseline_change' if load_change is not None and capacity_change is not None else 'unknown')
        samples.append({'timestamp': ts, 'ingress_mbps': ingress, 'effective_capacity_mbps': cap,
                        'exceeds_capacity': breached,
                        'ingress_capacity_ratio_pct': round(ingress/cap*100, 4) if valid and cap > 0 else None,
                        'excess_mbps': round(max(0, ingress-cap), 4) if valid else None,
                        'load_change_pct': round(load_change, 4) if load_change is not None else None,
                        'capacity_change_pct': round(capacity_change, 4) if capacity_change is not None else None,
                        'change_driver': driver, 'evidence': ev,
                        'routed_source_demand_mbps': round(offered, 4) if offered is not None else None,
                        'source_demand_minus_ingress_mbps': round(offered-ingress, 4) if offered is not None and ingress is not None else None,
                        'traffic_contributions': contributions, 'traffic_missing_service_ids': missing,
                        'service_observations': service,
                        'overload_and_service_decline': breached is True and any(s['state']=='declining' for s in service),
                        'observed_discard_mbps': observed(row, 'discarded_mbps')})
    valid = [s for s in samples if s['exceeds_capacity'] is not None]
    breached = [s for s in valid if s['exceeds_capacity']]
    joint = [s for s in breached if s['overload_and_service_decline']]
    losses = [s for s in valid if not s['exceeds_capacity'] and s['observed_discard_mbps'] is not None
              and s['observed_discard_mbps'] > .1]
    state = ('overload_with_service_decline' if joint else 'overload_observed' if breached else
             'loss_without_total_overload' if losses else 'within_capacity_in_observed_samples' if valid else 'unknown')
    representative = max(joint or breached or losses or valid, key=lambda s: s['excess_mbps']) if valid else None
    intervals = []
    step = timedelta(seconds=int(case['sampling_seconds']))
    for sample in samples:
        if not sample['exceeds_capacity']:
            continue
        timestamp = instant(sample['timestamp'])
        if intervals and instant(intervals[-1]['to_exclusive']) == timestamp:
            intervals[-1]['to_exclusive'] = (timestamp+step).isoformat()
            intervals[-1]['sample_count'] += 1
        else:
            intervals.append({'from':sample['timestamp'], 'to_exclusive':(timestamp+step).isoformat(), 'sample_count':1})
    missing = []
    if len(valid) < len(samples):
        missing.append(f'容量/到达流量有效样本 {len(valid)}/{len(samples)}，缺测区间不能排除过载')
    if any(s['traffic_missing_service_ids'] for s in samples):
        missing.append('部分源业务流量缺失或路由不匹配，源需求汇总不完整')
    missing += ['源端 offered 流量不等于逐跳到达流量；差额需结合上游丢弃、队列变化和未纳管流量核对',
                '需按业务/出端口队列、调度优先级及QoS配置解释选择性受损，当前数据不能推定调度策略']
    return {'object_type': kind, 'object_id': rid, 'assessment': state,
            'nominal_capacity_mbps': number(static, nominal_field),
            'nominal_capacity_source': {'source': 'nodes' if kind=='node' else 'links', 'object_id':rid, 'field':nominal_field},
            'baseline': baseline, 'expected_samples': len(samples), 'valid_samples': len(valid),
            'overload_sample_count': len(breached), 'overload_intervals': intervals, 'overload_observed_minutes': len(breached)*int(case['sampling_seconds'])/60,
            'first_overload_at': breached[0]['timestamp'] if breached else None,
            'overload_with_decline_sample_count': len(joint), 'representative_sample': representative,
            'samples': samples, 'missing_evidence': missing,
            'interpretation': '以同分钟实测到达流量与有效容量判断超限；标称容量仅作参考。超限与业务下降共现仍非因果证明。'}


def compare_relay_paths(tables, ctx, relay, capacities):
    """Normal and declining observations on different outgoing links at identical times."""
    comparisons = []
    for ts in ctx['times']:
        groups = defaultdict(list)
        for sid in _exposed(ctx, 'node', relay, ts):
            ex = ctx['membership'][(sid, instant(ts))]
            outgoing = {h['outgoing_link_id'] for h in ctx['hops'][ex['route_id']]
                        if h['node_id'] == relay and h['outgoing_link_id'] in ex['links']}
            if len(outgoing) != 1:
                continue  # no unambiguous outgoing segment, do not invent a control
            lid = next(iter(outgoing))
            observation = service_observation(ctx, sid, ts)
            observation['route_hop_provenance'] = [dict(h, source='route_hops') for h in ctx['hops'][ex['route_id']]
                                                   if h['node_id']==relay and h['outgoing_link_id']==lid]
            groups[lid].append(observation)
        declining = {lid for lid, group in groups.items() if any(s['state']=='declining' for s in group)}
        normal = {lid for lid, group in groups.items() if any(s['state']=='normal_sample' for s in group)}
        if not declining:
            continue
        details = []
        for lid, group in sorted(groups.items()):
            row = ctx['indexed']['link_metrics'].get((lid, instant(ts)))
            fields = [('snr_db','dB'), ('bit_error_rate','ratio'), ('effective_capacity_mbps','Mbps'),
                      ('ingress_mbps','Mbps'), ('discarded_mbps','Mbps')]
            details.append({'outgoing_link_id': lid, 'services': group,
                            'link_evidence': [evidence(row, f, unit, lid, 'link_metrics')
                                              for f, unit in fields if observed(row, f) is not None]})
        comparisons.append({'timestamp': ts, 'groups': details,
                            'different_outgoing_path_normal_control': any(a != b for a in declining for b in normal)})
    controls = [c for c in comparisons if c['different_outgoing_path_normal_control']]
    relay_capacity = capacities[('node', relay)]
    links_with_loss = sorted({g['outgoing_link_id'] for c in controls for g in c['groups']
                            if any(s['state']=='declining' for s in g['services']) and
                            any(e['field']=='discarded_mbps' and float(e['value'])>.1 for e in g['link_evidence'])})
    if controls and relay_capacity['overload_sample_count'] == 0 and relay_capacity['valid_samples'] == relay_capacity['expected_samples']:
        finding = 'path_selective_decline_without_observed_relay_overload'
        note = '同星同分钟有不同出站路径的正常对照，且中继总到达量未超过有效容量；优先核查受损出站链路，不能仅因共享中继星归因为整星过载。'
    elif controls:
        finding = 'path_selective_decline_relay_overload_not_excluded'
        note = '存在同星不同路径正常对照；选择性影响不能单独排除整星过载，仍需队列/QoS及缺测时段证据。'
    else:
        finding = 'no_synchronous_different_path_healthy_control'
        note = '尚无足够同星同分钟不同出站路径的正常对照；不据此宣称所有业务均受影响。'
    return {'relay_id': relay, 'assessment': finding, 'interpretation': note,
            'different_path_control_sample_count': len(controls), 'links_with_decline_and_discard': links_with_loss,
            'comparisons': comparisons,
            'missing_evidence': ['需要按业务的队列、调度优先级和分流策略；正常对照并非随机化因果实验']}


def diagnostic_context(tables, case, cutoff, snapshots, statuses):
    ctx = build_context(tables, case, cutoff, snapshots, statuses)
    environment = assess_environment(tables, case, ctx)
    capacities = {}
    for kind, ids in [('node', ctx['relays']), ('link', ctx['links'])]:
        for rid in ids:
            capacities[(kind, rid)] = assess_capacity(tables, case, ctx, kind, rid)
    return {'analysis_order': ['external_environment', 'relay_and_link_capacity', 'same_relay_path_controls'],
            'environment': environment,
            'capacity': {'order': 2, 'rules': RULES, 'resources': list(capacities.values())},
            'path_controls': [compare_relay_paths(tables, ctx, rid, capacities) for rid in ctx['relays']]}
