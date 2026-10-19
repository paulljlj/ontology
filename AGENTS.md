# Project continuation

- Read `HANDOFF.md` first. It is the authoritative current scope, division of labor, progress, setup and next-step record for branch `fengongdemo1`. Historical design/PPT documents are references, not proof of implemented features.
- Preserve the existing business-report workflow and unrelated user files. The satellite workflow is an additional entry, not a rewrite of the old system.
- We own routing, ontology, task execution, MCP integration, UI and downloads. The classmate owns diagnosis; it is not implemented/delivered in this snapshot. Never fabricate diagnosis results, infer a root cause from a manually supplied avoidance target, or describe a development fixture as a delivered algorithm.
- Runtime diagnosis/routing must not read `evaluation/`, the dataset generator, planted scenario labels, future observations or future recovery evidence. These are only for explicit fixture generation/evaluation. Keep `timestamp`, complete sampling interval and `available_at` cutoffs separate.
- The integration contract is `backend/app/domain/satellite_schemas.py` and its exported JSON Schema. Validate real source rows; do not execute code, SQL, commands or paths supplied inside diagnosis JSON.
- Use actual configured MCP tool calls and retain evidence. MCP errors must fail visibly, never silently fall back to file mode while claiming MCP success.
- Never mix `backend/mcp/python-runtime.lock` into the backend environment. It is a separate Windows/Python3.12 server runtime; use Node >=24 for Filesystem MCP.
- Do not run blanket `pytest` or destructive legacy integration tests. Use the explicit isolated test list in `HANDOFF.md`; some old tests delete fixed databases or the configured Neo4j graph.
- Do not commit `.env`, credentials, local databases, `.satellite-runtime`, dependencies, report output or temporary PPT/chart build folders. Keep observed CSV bytes unchanged; `.gitattributes` preserves their manifest hashes.
