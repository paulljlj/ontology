"""Graph import and MCP read-only relationship queries."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from .data import read_table

# Both graph backends return route membership only; domain metrics never go to MCP.
EXPOSURE_QUERY = '''MATCH (r:SatRoute {dataset_id:$dataset_id, case_id:$case_id})
WHERE r.effective_from <= $when AND $when < r.effective_to AND r.available_at <= $when
MATCH (s:SatService {dataset_id:$dataset_id})-[:USES {case_id:$case_id}]->(r)
MATCH (r)-[:HAS_HOP]->(h:SatHop)-[:AT_NODE]->(n:SatNode)
OPTIONAL MATCH (h)-[:OUTGOING]->(l:SatLink)
RETURN s.service_id AS service_id, r.route_id AS route_id,
[id IN collect(DISTINCT n.node_id) WHERE id IS NOT NULL] AS nodes,
[id IN collect(DISTINCT l.link_id) WHERE id IS NOT NULL] AS links'''


class LocalGraph:
    """Explicit CSV-only development/test mode, never an implicit MCP fallback."""
    def __init__(self, tables: dict):
        self.tables = tables

    def exposures(self, case_id: str, when: str) -> list[dict]:
        from .data import instant
        moment = instant(when)
        results = []
        for r in self.tables['routes']:
            if r['case_id'] != case_id or not (instant(r['effective_from']) <= moment
                and (not r['effective_to_exclusive'] or moment < instant(r['effective_to_exclusive']))
                and (not r.get('available_at') or instant(r['available_at']) <= moment)):
                continue
            hops = sorted((h for h in self.tables['route_hops'] if h['route_id'] == r['route_id'] and h['case_id'] == case_id),
                          key=lambda h: int(h['hop_index']))
            results.append({'service_id': r['service_id'], 'route_id': r['route_id'],
                            'nodes': [h['node_id'] for h in hops],
                            'links': [h['outgoing_link_id'] for h in hops if h['outgoing_link_id']]})
        return results


class MCPGraph:
    """Runs the released neo4j/mcp v1.6.0 binary through the MCP Python SDK."""
    def __init__(self, executable: str, env: dict | None = None):
        self.executable = executable
        self.env = env or {}

    async def _query(self, case_id: str, when: str) -> list[dict]:
        return (await self._query_many(case_id, [when]))[when]

    async def _query_many(self, case_id: str, when_values: list[str]) -> dict[str, list[dict]]:
        from mcp import StdioServerParameters
        settings = {**os.environ, **self.env, 'NEO4J_MCP_READ_ONLY': 'true',
                    'NEO4J_MCP_TELEMETRY': 'false'}
        for key in ('NEO4J_MCP_URI', 'NEO4J_MCP_USERNAME', 'NEO4J_MCP_PASSWORD',
                    'NEO4J_MCP_DATABASE'):
            if not settings.get(key):
                raise RuntimeError(key + ' must be set for MCP mode')
        server = StdioServerParameters(command=self.executable, args=[], env=settings)
        try:
            return await self._run_session(server, case_id, when_values)
        except Exception as exc:
            detail = '; '.join(str(e) for e in getattr(exc, 'exceptions', [exc]))
            raise RuntimeError('Neo4j MCP connection/query failed; check Docker database, credentials and server binary: ' + detail) from exc

    async def _run_session(self, server, case_id: str, when_values: list[str]) -> dict[str, list[dict]]:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client
        async with stdio_client(server) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                if not {'get-schema', 'read-cypher'}.issubset(tools) or 'write-cypher' in tools:
                    raise RuntimeError('expected read-only neo4j/mcp v1.6.0 tools')
                schema = await session.call_tool('get-schema', arguments={})
                if schema.isError:
                    raise RuntimeError('MCP get-schema failed: ' + str(schema.content))
                output = {}
                for when in when_values:
                    result = await session.call_tool('read-cypher', arguments={
                        'query': EXPOSURE_QUERY,
                        'params': {'dataset_id': 'satellite_demo_v1', 'case_id': case_id, 'when': when}})
                    if result.isError:
                        raise RuntimeError('MCP read-cypher failed: ' + str(result.content))
                    parts = [json.loads(c.text) for c in result.content if getattr(c, 'type', '') == 'text']
                    if not parts:
                        raise RuntimeError('MCP read-cypher returned no structured response')
                    data = parts[0]
                    if isinstance(data, dict):
                        data = data.get('records', data.get('results', data.get('rows', data)))
                    if not isinstance(data, list):
                        raise RuntimeError('unexpected MCP read-cypher response: ' + str(data)[:120])
                    output[when] = data
                return output

    def exposures(self, case_id: str, when: str) -> list[dict]:
        return asyncio.run(self._query(case_id, when))

    def exposures_many(self, case_id: str, when_values: list[str]) -> dict[str, list[dict]]:
        return asyncio.run(self._query_many(case_id, when_values))


def import_graph(root: str | Path, uri: str, user: str, password: str,
                 database: str = 'neo4j') -> dict:
    """Idempotent graph population; never reads evaluation files."""
    from neo4j import GraphDatabase
    tables = {name: read_table(root, name) for name in ('nodes','links','services','routes','route_hops')}
    driver = GraphDatabase.driver(uri, auth=(user, password))
    statements = [
        ('CREATE CONSTRAINT sat_node_key IF NOT EXISTS FOR (n:SatNode) REQUIRE (n.dataset_id,n.node_id) IS UNIQUE', None),
        ('CREATE CONSTRAINT sat_link_key IF NOT EXISTS FOR (n:SatLink) REQUIRE (n.dataset_id,n.link_id) IS UNIQUE', None),
        ('CREATE CONSTRAINT sat_svc_key IF NOT EXISTS FOR (n:SatService) REQUIRE (n.dataset_id,n.service_id) IS UNIQUE', None),
        ('CREATE CONSTRAINT sat_route_key IF NOT EXISTS FOR (n:SatRoute) REQUIRE (n.dataset_id,n.case_id,n.route_id) IS UNIQUE', None),
        ('CREATE CONSTRAINT sat_hop_key IF NOT EXISTS FOR (n:SatHop) REQUIRE (n.dataset_id,n.case_id,n.route_id,n.hop_index) IS UNIQUE', None),
        ('''UNWIND $rows AS r MERGE (n:SatNode {dataset_id:$ds,node_id:r.node_id})
            SET n.node_type=r.node_type''', tables['nodes']),
        ('''UNWIND $rows AS r MERGE (l:SatLink {dataset_id:$ds,link_id:r.link_id})
            WITH r,l MATCH (a:SatNode {dataset_id:$ds,node_id:r.source_node_id}),
              (b:SatNode {dataset_id:$ds,node_id:r.target_node_id})
            MERGE (l)-[:FROM]->(a) MERGE (l)-[:TO]->(b)''', tables['links']),
        ('''UNWIND $rows AS r MERGE (s:SatService {dataset_id:$ds,service_id:r.service_id})
            WITH r,s MATCH (a:SatNode {dataset_id:$ds,node_id:r.source_satellite_id}),
              (b:SatNode {dataset_id:$ds,node_id:r.destination_ground_station_id})
            MERGE (s)-[:SOURCE]->(a) MERGE (s)-[:DESTINATION]->(b)''', tables['services']),
        ('''UNWIND $rows AS r MATCH (s:SatService {dataset_id:$ds,service_id:r.service_id})
            MERGE (v:SatRoute {dataset_id:$ds,case_id:r.case_id,route_id:r.route_id})
            SET v.effective_from=r.effective_from,v.effective_to=r.effective_to_exclusive,v.available_at=r.available_at
            MERGE (s)-[:USES {case_id:r.case_id}]->(v)''', tables['routes']),
        ('''UNWIND $rows AS r MATCH (v:SatRoute {dataset_id:$ds,case_id:r.case_id,route_id:r.route_id}),
              (n:SatNode {dataset_id:$ds,node_id:r.node_id})
            MERGE (h:SatHop {dataset_id:$ds,case_id:r.case_id,route_id:r.route_id,hop_index:toInteger(r.hop_index)})
            MERGE (v)-[:HAS_HOP]->(h) MERGE (h)-[:AT_NODE]->(n)''', tables['route_hops']),
        ('''UNWIND $rows AS r WITH r WHERE r.outgoing_link_id <> ''
            MATCH (h:SatHop {dataset_id:$ds,case_id:r.case_id,route_id:r.route_id,hop_index:toInteger(r.hop_index)}),
              (l:SatLink {dataset_id:$ds,link_id:r.outgoing_link_id})
            MERGE (h)-[:OUTGOING]->(l)''', tables['route_hops'])]
    try:
        with driver.session(database=database) as session:
            for stmt, rows in statements:
                if rows is None:
                    session.run(stmt).consume()
                else:
                    for offset in range(0, len(rows), 500):
                        session.run(stmt, ds='satellite_demo_v1', rows=rows[offset:offset+500]).consume()
    finally:
        driver.close()
    return {k:len(v) for k,v in tables.items()}
