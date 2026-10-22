"""Only test code reads evaluation/ to check independently generated answers."""
import json
import unittest
from pathlib import Path
from satellite_diagnosis import analyze_case, LocalGraph, load_case

ROOT=Path(__file__).resolve().parents[3] / 'data-output' / 'satellite_demo_v1'

class EvaluationTests(unittest.TestCase):
    def test_planted_objects_are_not_looked_up_during_diagnosis(self):
        ground_truth=json.loads((ROOT/'evaluation'/'ground_truth.json').read_text(encoding='utf-8'))
        for item in ground_truth['cases']:
            cid=item['case_id']
            report=analyze_case(ROOT,cid,graph=LocalGraph(load_case(ROOT,cid)['tables']))
            if item['expected_handling']=='major_anomaly':
                self.assertEqual(item['planted_object_id'],report['conclusion_and_missing_evidence']['priority_object'])
            if item['expected_handling']=='insufficient_cause_evidence':
                self.assertEqual('limited',report['root_cause_candidates'][0]['evidence_strength'])
            if item['expected_handling']=='normal_service':
                self.assertEqual(0,report['anomaly_overview']['major_count'])

if __name__=='__main__':
    unittest.main()
