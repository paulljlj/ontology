"""New diagnostic phases: only observed input; no evaluation/ access here."""
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from satellite_diagnosis import analyze_case, load_case, LocalGraph
from satellite_diagnosis.context import assess_capacity, build_context, compare_relay_paths
from satellite_diagnosis.diagnosis import number, resource_signals, service_status

ROOT = Path(__file__).resolve().parents[3] / 'data-output' / 'satellite_demo_v1'


@pytest.fixture(scope='module')
def reports():
    result = {}
    for cid in ('CASE-001', 'CASE-003', 'CASE-004', 'CASE-007', 'CASE-008'):
        data = load_case(ROOT, cid)
        result[cid] = analyze_case(ROOT, cid, graph=LocalGraph(data['tables']))
    return result


def resource(report, rid):
    return next(r for r in report['diagnostic_process']['capacity']['resources'] if r['object_id']==rid)


def environment(report, rid='SAT-20'):
    return next(r for r in report['diagnostic_process']['environment']['objects'] if r['object_id']==rid)


def test_environment_first_and_not_automatic_cause(reports):
    assert reports['CASE-004']['diagnostic_process']['analysis_order'][0]=='external_environment'
    env = environment(reports['CASE-004'])
    assert env['assessment']=='proxy_device_service_cooccurrence'
    sample = env['representative_sample']
    assert sample['positive_device_response']
    assert any(s['state']=='declining' for s in sample['service_observations'])
    assert all(e['timestamp']==sample['timestamp'] for e in sample['device_responses'])
    env = environment(reports['CASE-007'])
    assert env['assessment']=='proxy_elevated_without_observed_device_response'
    assert env['elevated_sample_count'] > 0
    assert not reports['CASE-007']['root_cause_candidates']
    data = load_case(ROOT, 'CASE-004')
    signals = resource_signals(data['tables'], data['case'], 'node', 'SAT-20')
    assert not any(e['field']=='radiation_proxy_counts_per_min' for e in signals['contrary'])
    assert any(e['field']=='radiation_proxy_counts_per_min' for e in signals['context'])


def test_capacity_demand_increase_vs_capacity_loss(reports):
    cap = resource(reports['CASE-001'], 'SAT-20')
    assert cap['assessment']=='overload_with_service_decline'
    s = cap['representative_sample']
    assert s['ingress_mbps'] > s['effective_capacity_mbps']
    assert s['change_driver']=='demand_growth'
    assert s['traffic_contributions']
    assert all(e['record_id'] and e['route_id'] for e in s['traffic_contributions'])
    assert s['routed_source_demand_mbps']==pytest.approx(sum(float(e['value']) for e in s['traffic_contributions']))
    link = resource(reports['CASE-003'], 'L-SAT-20-GS-01')
    assert link['assessment']=='overload_with_service_decline'
    assert link['representative_sample']['change_driver']=='capacity_reduction'
    assert link['representative_sample']['capacity_change_pct'] < -80
    assert resource(reports['CASE-003'], 'SAT-20')['overload_sample_count']==0
    assert resource(reports['CASE-004'], 'SAT-20')['assessment']=='loss_without_total_overload'


def test_same_relay_different_outgoing_healthy_controls(reports):
    report = reports['CASE-003']
    comparison = next(x for x in report['diagnostic_process']['path_controls'] if x['relay_id']=='SAT-20')
    assert comparison['assessment']=='path_selective_decline_without_observed_relay_overload'
    pair = next(c for c in comparison['comparisons'] if c['different_outgoing_path_normal_control'])
    bad = next(g for g in pair['groups'] if g['outgoing_link_id']=='L-SAT-20-GS-01')
    assert {s['service_id'] for s in bad['services'] if s['state']=='declining'}=={'SVC-001','SVC-003','SVC-006','SVC-008'}
    normal = {s['service_id'] for g in pair['groups'] for s in g['services'] if s['state']=='normal_sample'}
    assert normal=={'SVC-002','SVC-004','SVC-005','SVC-007','SVC-009','SVC-010'}
    for group in pair['groups']:
        for service in group['services']:
            assert service['evidence']['timestamp']==pair['timestamp']


def test_missing_telemetry_cannot_exclude_overload(reports):
    cap = resource(reports['CASE-008'], 'SAT-20')
    assert cap['assessment']=='unknown'
    assert cap['valid_samples']==0
    assert cap['representative_sample'] is None
    assert all(s['ingress_mbps'] is None and s['exceeds_capacity'] is None for s in cap['samples'])
    assert environment(reports['CASE-008'])['assessment']=='unknown'


def test_all_new_evidence_precedes_cutoff(reports):
    def walk(obj):
        if isinstance(obj, dict):
            if 'record_id' in obj:
                assert obj['source'] in {'node_metrics','link_metrics','service_metrics','traffic','events'}
                assert obj['record_id']
                assert datetime.fromisoformat(obj['available_at']) <= end
                assert datetime.fromisoformat(obj['timestamp']) < end
                assert obj['case_id']==cid
            for value in obj.values():
                walk(value)
        elif isinstance(obj,list):
            for value in obj:
                walk(value)
    for cid, report in reports.items():
        end = datetime.fromisoformat(report['as_of'])
        walk(report['diagnostic_process'])


@pytest.fixture
def small_context():
    data = load_case(ROOT, 'CASE-003')
    case, tables = data['case'], data['tables']
    snapshots = {case['analysis_start']: LocalGraph(tables).exposures(case['case_id'], case['analysis_start'])}
    ctx = build_context(tables, case, data['cutoff'], snapshots,
                        service_status(tables, case, data['rules'], data['cutoff']))
    ctx['times'] = ctx['times'][:1]
    return data, ctx


@pytest.mark.parametrize('load,capacity,expected', [(1000,1000,False),(1000.1,1000,True),(1,0,True),(0,0,False),('',1000,None),(-1,1000,None)])
def test_capacity_boundaries(small_context, load, capacity, expected):
    data, ctx = small_context
    ts = datetime.fromisoformat(ctx['times'][0])
    row = ctx['indexed']['node_metrics'][('SAT-20',ts)]
    row.update(ingress_mbps=str(load),effective_capacity_mbps=str(capacity))
    result = assess_capacity(data['tables'],data['case'],ctx,'node','SAT-20')
    sample = result['samples'][0]
    assert sample['exceeds_capacity'] is expected
    if capacity==0:
        assert sample['ingress_capacity_ratio_pct'] is None


def test_unknown_service_not_healthy_and_missing_traffic_not_zero(small_context):
    data, ctx = small_context
    ts = datetime.fromisoformat(ctx['times'][0])
    # Remove all six otherwise healthy same-relay controls.
    for sid in ('SVC-002','SVC-004','SVC-005','SVC-007','SVC-009','SVC-010'):
        del ctx['indexed']['service_metrics'][(sid,ts)]
    del ctx['indexed']['traffic'][('SVC-001',ts)]
    cap = assess_capacity(data['tables'],data['case'],ctx,'node','SAT-20')
    assert cap['samples'][0]['routed_source_demand_mbps'] is None
    assert 'SVC-001' in cap['samples'][0]['traffic_missing_service_ids']
    result = compare_relay_paths(data['tables'],ctx,'SAT-20',{('node','SAT-20'):cap})
    assert result['different_path_control_sample_count']==0
    states = [s['state'] for g in result['comparisons'][0]['groups'] for s in g['services']]
    assert 'unknown' in states and 'normal_sample' not in states


def test_late_traffic_and_telemetry_excluded():
    from satellite_diagnosis.data import read_table
    def delayed(root, table, case_id=None):
        rows = read_table(root,table,case_id)
        if table in ('node_metrics','traffic'):
            for row in rows:
                if row.get('timestamp','').startswith('2026-09-15T10:00:'):
                    row['available_at']='2026-09-15T11:00:00.000+08:00'
        return rows
    with patch('satellite_diagnosis.data.read_table',side_effect=delayed):
        data = load_case(ROOT,'CASE-001')
    assert not any(r['timestamp'].startswith('2026-09-15T10:00:') for r in data['tables']['node_metrics'])
    assert not any(r['timestamp'].startswith('2026-09-15T10:00:') for r in data['tables']['traffic'])


def test_traffic_route_mismatch_is_unknown(small_context):
    data, ctx = small_context
    ts = datetime.fromisoformat(ctx['times'][0])
    ctx['indexed']['traffic'][('SVC-001',ts)]['route_id']='old-route'
    cap = assess_capacity(data['tables'],data['case'],ctx,'node','SAT-20')
    assert cap['samples'][0]['routed_source_demand_mbps'] is None
    assert cap['samples'][0]['traffic_missing_service_ids']==['SVC-001']


def test_nonfinite_number_is_missing():
    for value in ('NaN','inf','-Infinity',''):
        assert number({'x':value},'x') is None


def test_environment_demo_threshold_boundary(small_context):
    from satellite_diagnosis.context import assess_environment, observed
    data, ctx = small_context
    row = ctx['indexed']['node_metrics'][('SAT-20', datetime.fromisoformat(ctx['times'][0]))]
    row['radiation_proxy_counts_per_min']='99.999'
    env = assess_environment(data['tables'], data['case'],ctx)
    assert next(x for x in env['objects'] if x['object_id']=='SAT-20')['elevated_sample_count']==0
    row['radiation_proxy_counts_per_min']='100'
    env = assess_environment(data['tables'], data['case'],ctx)
    assert next(x for x in env['objects'] if x['object_id']=='SAT-20')['elevated_sample_count']==1
    assert observed({'measurement_status':'observed','snr_db':'-2'},'snr_db')==-2


def test_capacity_missing_sample_breaks_overload_interval(small_context):
    from datetime import timedelta
    data, ctx = small_context
    start = datetime.fromisoformat(ctx['times'][0])
    ctx['times'] = [(start+timedelta(minutes=i)).isoformat(timespec='milliseconds') for i in range(3)]
    for ts in ctx['times']:
        ctx['indexed']['node_metrics'][('SAT-20',datetime.fromisoformat(ts))].update(ingress_mbps='1001',effective_capacity_mbps='1000')
    del ctx['indexed']['node_metrics'][('SAT-20',start+timedelta(minutes=1))]
    cap = assess_capacity(data['tables'],data['case'],ctx,'node','SAT-20')
    assert cap['valid_samples']==2
    assert [i['sample_count'] for i in cap['overload_intervals']]==[1,1]


def test_context_follows_temporal_route_versions():
    data = load_case(ROOT,'CASE-006', '2026-09-15T10:31:00+08:00')
    case, tables = data['case'], data['tables']
    # Route switch at 10:00 must use the new route, not a stale pre-switch snapshot.
    graph = LocalGraph(tables)
    snapshots = {t:graph.exposures('CASE-006',t) for t in
                 ('2026-09-15T09:59:00.000+08:00',case['analysis_start'])}
    ctx = build_context(tables,case,data['cutoff'],snapshots,service_status(tables,case,data['rules'],data['cutoff']))
    new_route = ctx['membership'][('SVC-001',datetime.fromisoformat(case['analysis_start']))]['route_id']
    old_route = next(x['route_id'] for x in snapshots['2026-09-15T09:59:00.000+08:00'] if x['service_id']=='SVC-001')
    assert new_route!=old_route
    sample = ctx['indexed']['traffic'][('SVC-001',datetime.fromisoformat(case['analysis_start']))]
    assert sample['route_id']==new_route


def test_environment_after_decline_not_initial_cause(small_context):
    from datetime import timedelta
    from satellite_diagnosis.context import assess_environment
    data, ctx = small_context
    start = datetime.fromisoformat(ctx['times'][0])
    ctx['times'] = [(start+timedelta(minutes=i)).isoformat(timespec='milliseconds') for i in range(2)]
    first = ctx['indexed']['node_metrics'][('SAT-20',start)]
    later = ctx['indexed']['node_metrics'][('SAT-20',start+timedelta(minutes=1))]
    first['radiation_proxy_counts_per_min']='2'
    later.update(radiation_proxy_counts_per_min='200',seu_events_per_min='7')
    env = next(x for x in assess_environment(data['tables'],data['case'],ctx)['objects'] if x['object_id']=='SAT-20')
    assert env['timeline']['temporal_relation']=='proxy_after_first_observed_decline'
    assert env['timeline']['proxy_to_first_service_decline_seconds']==-60
    assert env['causal_status']=='not_established'


def test_within_capacity_evidence_opposes_total_overload(reports):
    candidate = next(c for c in reports['CASE-003']['root_cause_candidates'] if c['object_id']=='SAT-20')
    assert candidate['diagnostic_assessments']['capacity']=='within_capacity_in_observed_samples'
    assert any(e['field']=='effective_capacity_mbps' for e in candidate['counter_evidence'])
    assert not any(e['field']=='effective_capacity_mbps' for e in candidate['supporting_evidence'])
