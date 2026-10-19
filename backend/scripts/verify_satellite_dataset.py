"""Portable integrity checks; reads observed CSVs and metadata, never evaluation."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TABLES = {"cases", "nodes", "links", "services", "routes", "route_hops", "traffic",
          "node_metrics", "link_metrics", "service_metrics", "events"}


def verify(root: Path) -> dict:
    root = root.resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    dictionary = json.loads((root / "data_dictionary.json").read_text(encoding="utf-8-sig"))
    expected = {f"observed/{name}.csv" for name in TABLES}
    catalog = manifest["observation_csv_files"]
    descriptions = {item["file"]: item for item in dictionary["tables"]}
    if len(catalog) != len(TABLES) or {item["file"] for item in catalog} != expected or set(descriptions) != expected:
        raise ValueError("Expected exactly the 11 observed CSVs; metadata cannot redirect to other inputs")
    results = []
    for item in catalog:
        relative = item["file"]
        file = (root / relative).resolve()
        file.relative_to((root / "observed").resolve())
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        definition = descriptions[relative]
        if digest != item["sha256"] or digest != definition["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {relative}; do not normalize CSV line endings")
        with file.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source)
            header = next(reader)
            if header != [field["name"] for field in definition["fields"]] or len(header) != definition["columns"]:
                raise ValueError(f"CSV header mismatch: {relative}")
            count = 0
            for count, row in enumerate(reader, 1):
                if len(row) != len(header):
                    raise ValueError(f"CSV width mismatch: {relative}, data row {count}")
        if count != item["rows"] or count != definition["rows"]:
            raise ValueError(f"Row count mismatch: {relative}")
        results.append({"file": relative, "rows": count, "sha256_verified": True, "headers_verified": True})
    return {"status": "passed", "csv_files": len(results), "total_rows": sum(r["rows"] for r in results),
            "evaluation_read": False, "scope": "file integrity, not diagnosis accuracy", "tables": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT / "data-output" / "satellite_demo_v1")
    args = parser.parse_args()
    print(json.dumps(verify(args.data_root), ensure_ascii=True, indent=2))
