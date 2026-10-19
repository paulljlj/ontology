"""Read-only CLI for joint satellite rerouting; stdout is a JSON result."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.application.satellite_routing import optimize_routes


def main() -> None:
    parser = argparse.ArgumentParser(description="模拟备选通信路径；只读，不切换真实网络")
    parser.add_argument("--data-root", type=Path, default=BACKEND_ROOT.parent / "data-output" / "satellite_demo_v1")
    parser.add_argument("--case", default="CASE-001")
    parser.add_argument("--avoid", nargs="+", default=["SAT-20"])
    parser.add_argument("--at")
    parser.add_argument("--as-of")
    parser.add_argument("--services", nargs="+")
    parser.add_argument("--max-utilization-pct", type=float, default=85)
    parser.add_argument("--max-latency-ms", type=float, default=150)
    parser.add_argument("--max-options", type=int, default=3)
    args = parser.parse_args()
    result = optimize_routes(args.data_root, args.case, args.avoid, at=args.at, as_of=args.as_of,
                             service_ids=args.services, max_utilization_pct=args.max_utilization_pct,
                             max_latency_ms=args.max_latency_ms, max_options=args.max_options)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
