"""Export the in-memory OWL ontology to an RDF/XML file."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain import ontology  # noqa: E402


def main() -> None:
    output = ontology.export_ontology()
    print(f"Exported ontology to {output}")


if __name__ == "__main__":
    main()