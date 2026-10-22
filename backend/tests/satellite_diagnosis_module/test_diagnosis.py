"""Offline tests deliberately use LocalGraph; they are NOT an MCP integration pass."""
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from satellite_diagnosis import analyze_case, load_case, read_table, LocalGraph
from satellite_diagnosis.diagnosis import runs, service_status
from satellite_diagnosis.graph import EXPOSURE_QUERY

ROOT = Path(__file__).resolve().parents[3] / 'data-output' / 'satellite_demo_v1'


def local(case, cutoff=None):
    return analyze_case(ROOT, case, cutoff, LocalGraph(load_case(ROOT,case,cutoff)['tables']))


class DiagnosisTests(unittest.TestCase):
    def test_all_cases(self):
        expected={'CASE-001':('SAT-20',10),'CASE-002':('GS-01',7),
                  'CASE-003':('L-SAT-20-GS-01',4),'CASE-004':('SAT-20',10),
                  'CASE-005':(None,0),'CASE-006':(None,0),
                  'CASE-007':(None,0),'CASE-008':('SAT-20',10)}
        for case,(candidate,count) in expected.items():
            with self.subTest(case=case):
                r=local(case)
                self.assertEqual(count,r['anomaly_overview']['major_count'])
                self.assertEqual(candidate,r['conclusion_and_missing_evidence']['priority_object'])
                self.assertEqual('local_test_only',r['graph_backend'])

    def test_watch_and_planned_and_missing(self):
        a=local('CASE-001')
        self.assertEqual({'SVC-015','SVC-016','SVC-017','SVC-018'},
                         {w['service_id'] for w in a['minor_anomalies']['watch']})
        a=local('CASE-005')
        self.assertFalse(a['minor_anomalies']['watch'])
        self.assertEqual(4,len(a['minor_anomalies']['observing']))
        a=local('CASE-006')
        self.assertEqual(5,len(a['minor_anomalies']['observing']))
        self.assertTrue(all(s['classification']=='planned_transition' and s['planned_change_evidence']['record_id']=='EV-C6-PLAN'
                            for s in a['minor_anomalies']['observing']))
        a=local('CASE-007')
        self.assertEqual([],a['root_cause_candidates'])
        a=local('CASE-008')
        self.assertTrue(a['data_quality']['telemetry_gaps'])
        self.assertEqual('limited',a['root_cause_candidates'][0]['evidence_strength'])

    def test_evidence_temporal_and_provenance(self):
        r=local('CASE-001')
        end=datetime.fromisoformat(r['as_of'])
        for candidate in r['root_cause_candidates']:
            self.assertTrue(candidate['supporting_evidence'])
            for entry in candidate['supporting_evidence'] + candidate['counter_evidence']:
                self.assertTrue(entry['record_id'])
                self.assertLessEqual(datetime.fromisoformat(entry['available_at']),end)
                self.assertLess(datetime.fromisoformat(entry['timestamp']),end)
        # A future close event must never appear in initial diagnosis.
        self.assertNotIn('EV-C1-A1-CLOSE',json.dumps(r,ensure_ascii=False))
        self.assertFalse(any(e.get('event_id')=='EV-C1-A1-CLOSE' for e in load_case(ROOT,'CASE-001')['tables']['events']))

    def test_threshold_contiguity(self):
        xs=[{'timestamp':f'2026-09-15T10:{i:02}:00+08:00','drop_pp':v}
            for i,v in enumerate([5,5.1,5.4,None,5.6,5.7,5.8])]
        self.assertEqual([2,3],[len(r) for r in runs(xs, lambda x:x>5,1)])
        xs[5]['timestamp']='2026-09-15T10:10:00+08:00'
        self.assertEqual([2,1,1,1],[len(r) for r in runs(xs,lambda x:x>5,1)])

    def test_no_evaluation_input_or_cross_case(self):
        with self.assertRaises(ValueError):
            read_table(ROOT,'ground_truth')
        with self.assertRaises(ValueError):
            read_table(ROOT,'../evaluation/ground_truth')
        case=load_case(ROOT,'CASE-001')
        for name,rows in case['tables'].items():
            if rows and 'case_id' in rows[0]:
                self.assertEqual({'CASE-001'},{r['case_id'] for r in rows})
        with patch('satellite_diagnosis.data.read_table',side_effect=AssertionError('diagnosis touched file')):
            # path validation rejects evaluation before any table read
            with self.assertRaises(ValueError):
                read_table(ROOT,'evaluation/ground_truth')

    def test_entirely_absent_service_is_not_healthy(self):
        data = load_case(ROOT, 'CASE-001')
        tables = dict(data['tables'])
        tables['service_metrics'] = [r for r in tables['service_metrics']
                                      if r['service_id'] != 'SVC-001']
        status = next(x for x in service_status(tables, data['case'], data['rules'], data['cutoff'])
                      if x['service_id'] == 'SVC-001')
        self.assertEqual('unobserved', status['classification'])
        self.assertIsNone(status['baseline_availability_pct'])
        self.assertEqual(15, status['missing_minutes'])

    def test_allowlist_rejects_symlink_to_evaluation(self):
        from satellite_diagnosis.data import load_allowlist
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'observed').mkdir()
            (base / 'evaluation').mkdir()
            secret = base / 'evaluation' / 'ground_truth.json'
            secret.write_text('SECRET', encoding='utf-8')
            (base / 'manifest.json').write_text(json.dumps({
                'diagnosis_allowlist': ['observed/cases.csv']}), encoding='utf-8')
            try:
                (base / 'observed' / 'cases.csv').symlink_to(secret)
            except OSError:
                self.skipTest('current Windows account cannot create symlinks')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                load_allowlist(base)

    def test_temporal_route_is_not_start_window_route(self):
        data = load_case(ROOT, 'CASE-006')
        graph = LocalGraph(data['tables'])
        early = graph.exposures('CASE-006', '2026-09-15T09:59:00+08:00')
        late = graph.exposures('CASE-006', '2026-09-15T10:00:00+08:00')
        early_route = next(r['route_id'] for r in early if r['service_id'] == 'SVC-001')
        late_route = next(r['route_id'] for r in late if r['service_id'] == 'SVC-001')
        self.assertNotEqual(early_route, late_route)

    def test_mcp_query_is_bound_and_case_scoped(self):
        self.assertIn('case_id:$case_id',EXPOSURE_QUERY)
        self.assertIn('dataset_id:$dataset_id',EXPOSURE_QUERY)
        self.assertIn('$when',EXPOSURE_QUERY)
        with self.assertRaises(ValueError):
            load_case(ROOT,'CASE-XYZ')

    def test_observation_at_prevents_later_samples_from_entering_diagnosis(self):
        from satellite_diagnosis.data import instant
        at = '2026-09-15T10:02:00+08:00'
        data = load_case(ROOT, 'CASE-001', '2026-09-15T10:16:00+08:00', at)
        for table in ('traffic', 'node_metrics', 'link_metrics', 'service_metrics'):
            self.assertTrue(all(instant(row['timestamp']) <= instant(at) for row in data['tables'][table]))
        graph = LocalGraph(data['tables'])
        report = analyze_case(ROOT, 'CASE-001', '2026-09-15T10:16:00+08:00', graph,
                              observation_at=at)
        self.assertEqual('2026-09-15T10:03:00+08:00', report['analysis_window']['to_exclusive'])
        for candidate in report['root_cause_candidates']:
            for item in candidate['supporting_evidence'] + candidate['counter_evidence']:
                if item.get('timestamp'):
                    self.assertLessEqual(instant(item['timestamp']), instant(at))

    def test_public_function_does_not_silently_fallback(self):
        from satellite_diagnosis import MCPGraph
        with patch.object(MCPGraph,'exposures_many',side_effect=RuntimeError('real MCP unavailable')):
            with self.assertRaisesRegex(RuntimeError,'real MCP unavailable'):
                analyze_case(ROOT,'CASE-001')


if __name__=='__main__':
    unittest.main()
