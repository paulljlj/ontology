"""Run our planning/integration module with an isolated local SQLite database."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="CASE-001")
    parser.add_argument("--avoid", nargs="+", default=None, help="optional manual route-avoidance override")
    parser.add_argument("--at")
    parser.add_argument("--as-of")
    parser.add_argument("--diagnosis-json", type=Path)
    parser.add_argument("--auto-diagnosis", action=argparse.BooleanOptionalAction, default=True,
                        help="run the integrated collaborator module (default: enabled)")
    parser.add_argument("--diagnosis-backend", choices=("local", "neo4j_mcp"), default="local")
    parser.add_argument("--full", action="store_true", help="print the full structured report")
    args = parser.parse_args()
    runtime = ROOT / ".satellite-runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    os.environ["DATABASE_URL"] = "sqlite:///" + (runtime / "cli-demo.db").as_posix()
    os.environ["FEISHU_EVENT_ENABLED"] = "false"
    os.environ["LLM_PROVIDER"] = "rule-based"
    sys.path.insert(0, str(ROOT / "backend"))
    from app.domain.satellite_schemas import SatelliteRunCreate
    from app.application.satellite_workflow import create_satellite_run, execute_satellite_run
    from app.infrastructure.database import Base, engine, session_scope
    from app.infrastructure.orm import WorkflowRunORM, ArtifactORM
    from sqlalchemy import select
    Base.metadata.create_all(engine)
    diagnosis = json.loads(args.diagnosis_json.read_text(encoding="utf-8-sig")) if args.diagnosis_json else None
    auto_diagnosis = bool(args.auto_diagnosis and diagnosis is None)
    avoid = args.avoid if args.avoid is not None else ([] if auto_diagnosis or diagnosis else ["SAT-20"])
    payload = SatelliteRunCreate(case_id=args.case, avoid_objects=avoid, at=args.at, as_of=args.as_of,
        auto_diagnosis=auto_diagnosis, diagnosis_graph_backend=args.diagnosis_backend, diagnosis=diagnosis)
    identity = create_satellite_run(payload)
    execute_satellite_run(identity)
    with session_scope() as session:
        run = session.get(WorkflowRunORM, identity)
        report = run.summary.get("satellite_report", {})
        result = {"run_id": identity, "status": run.status, "error": run.error,
            "case_id": args.case, "diagnosis_status": report.get("diagnosis_status"),
            "execution_mode": run.result_contract["execution_mode"], "mcp_call_count": run.summary.get("mcp_call_count", 0),
            "routing_status": report.get("route_options", {}).get("status"),
            "proposal_count": len(report.get("route_options", {}).get("proposals", [])),
            "artifacts": [{"name": x.name, "path": x.path} for x in session.scalars(select(ArtifactORM).where(ArtifactORM.run_id == identity)).all()]}
        if args.full: result["report"] = report
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if run.status == "succeeded" else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
