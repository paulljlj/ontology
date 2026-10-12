"""Class-name and relation-type enums auto-derived from the OWL ontology.

This module used to hand-code ``ClassName`` and ``RelationType`` as StrEnums,
duplicating what is already declared in :mod:`app.domain.ontology`. After the
OWL migration those hardcoded copies became a second source of truth, so they
are now built dynamically from ``ontology.list_classes()`` and
``ontology.list_relations()``. The access pattern (``ClassName.FEATURE``,
``RelationType.HAS_TASK``) is unchanged, so existing call sites need no edits.
"""
from __future__ import annotations

import re
from enum import StrEnum

from app.domain import ontology


def _to_enum_member(name: str) -> str:
    """Convert a CamelCase / ACRONYM class name to an UPPER_SNAKE enum member name.

    "DataModel" -> "DATA_MODEL"; "Feature" -> "FEATURE"; "ADR" -> "ADR";
    "ExecutionLog" -> "EXECUTION_LOG"; "FeishuMessage" -> "FEISHU_MESSAGE".
    """
    # Insert underscore between lowercase-then-uppercase (CamelCase boundary).
    s1 = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    # Insert underscore between acronym + CamelCase (e.g. "XMLHttp" -> "XML_Http").
    s2 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s1)
    return s2.upper()


_class_members: dict[str, str] = {
    _to_enum_member(name): name
    for name in ontology.list_classes()
}
ClassName = StrEnum("ClassName", _class_members)


_relation_members: dict[str, str] = {
    name: name for name in ontology.list_relations()
}
RelationType = StrEnum("RelationType", _relation_members)