"""Live integration test. Set SATELLITE_MCP_INTEGRATION=1 after Docker+import."""
import os
import unittest
from pathlib import Path
from satellite_diagnosis import MCPGraph, analyze_case

ROOT=Path(__file__).resolve().parents[3] / 'data-output' / 'satellite_demo_v1'

@unittest.skipUnless(os.environ.get('SATELLITE_MCP_INTEGRATION')=='1',
                     'requires live Neo4j and official MCP server, explicitly opt in')
class LiveMCPTests(unittest.TestCase):
    def test_official_mcp_tool_and_diagnosis(self):
        binary=os.environ['NEO4J_MCP_BIN']
        graph=MCPGraph(binary)
        rows=graph.exposures('CASE-001','2026-09-15T10:00:00.000+08:00')
        self.assertEqual(18,len(rows))
        report=analyze_case(ROOT,'CASE-001',graph=graph)
        self.assertEqual('mcp',report['graph_backend'])
        self.assertEqual('SAT-20',report['conclusion_and_missing_evidence']['priority_object'])

if __name__=='__main__':
    unittest.main()
