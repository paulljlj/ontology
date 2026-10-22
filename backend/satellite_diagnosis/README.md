# Satellite diagnosis package

This package is the classmate/B delivery imported from the sibling `Agent/Agent/satellite_diagnosis` workspace on 2026-10-22. The CLI dataset default now points to this repository's `data-output/satellite_demo_v1`. `load_case`/`analyze_case` also received a backward-compatible optional `observation_at` bound so a route snapshot earlier than `as_of` cannot see later samples.

Public entry point:

```python
from satellite_diagnosis import analyze_case, load_case, LocalGraph
```

The application does not directly expose the multi-megabyte raw dictionary. `app/application/satellite_diagnosis_adapter.py` converts it to the stable, evidence-validated workflow contract and publishes the raw dictionary as a separate audit artifact.

Run the standalone local diagnostic from `backend/`:

```powershell
python -m satellite_diagnosis diagnose --case CASE-001 --graph-backend local --output reports
```

The local graph is explicitly marked `local_test_only`. Optional official Neo4j MCP setup is documented in `backend/mcp/neo4j/README.md`. Runtime diagnosis reads only the manifest diagnosis allowlist; `evaluation/` is reserved for explicit tests.
