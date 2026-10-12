"""Load exported ontology into a sandboxed World and run Pellet consistency checks."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from owlready2 import OwlReadyInconsistentOntologyError, World, sync_reasoner_pellet  # noqa: E402

from app.domain import ontology  # noqa: E402


def main() -> int:
    owl_path = ontology.DEFAULT_OWL_PATH
    if not owl_path.exists():
        ontology.export_ontology(owl_path)

    world = World()
    try:
        loaded = world.get_ontology(str(owl_path.resolve())).load()
        sync_reasoner_pellet([loaded], infer_property_values=True, debug=0)
    except OwlReadyInconsistentOntologyError as exc:
        print(f"Inconsistent ontology: {exc}")
        return 1
    except Exception as exc:
        print(f"Pellet check failed: {exc}")
        return 2
    finally:
        world.close()

    print("Pellet consistency check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())