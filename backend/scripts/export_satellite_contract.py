"""Export the shared diagnosis JSON Schema from the authoritative Pydantic model."""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.domain.satellite_schemas import DiagnosisInput


if __name__ == "__main__":
    target = ROOT / "docs" / "satellite-diagnosis.schema.json"
    target.write_text(json.dumps(DiagnosisInput.model_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
