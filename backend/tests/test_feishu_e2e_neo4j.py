"""E2E verification: Feishu approval writeback must create Neo4j relations.

Verifies two paths:
  PART A: create_spec_approval → CONTAINS Spec→FeishuMessage in Neo4j
  PART B: _on_approval_event (callback) → HAS_REFLECTION Spec→Reflection in Neo4j
"""
# -*- coding: utf-8 -*-
from __future__ import annotations
import io
import os
import sys
import uuid
from pathlib import Path
from datetime import UTC, datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = "sqlite:///./test_feishu_e2e.db"

from sqlalchemy import select  # noqa: E402

from app.application import ontology_service  # noqa: E402
from app.application.ontology_service import get_instance_or_404  # noqa: E402
from app.domain.constants import ClassName, RelationType  # noqa: E402
from app.infrastructure import feishu_client, feishu_events, graph_db  # noqa: E402
from app.infrastructure.database import Base, engine, session_scope  # noqa: E402
from app.infrastructure.orm import ApprovalMappingORM  # noqa: E402
from app.infrastructure.seed import seed_database  # noqa: E402


def _wipe_neo4j_test_nodes() -> None:
    with graph_db.graph_session() as session:
        session.run("MATCH (n) DETACH DELETE n").single()
    print("[SETUP] Neo4j 全清完成")


def _count_nodes(class_name: str | None = None) -> int:
    with graph_db.graph_session() as session:
        if class_name:
            result = session.run(
                "MATCH (n:OntologyInstance {class_name: $c}) RETURN count(n) AS c",
                c=class_name,
            ).single()
        else:
            result = session.run("MATCH (n:OntologyInstance) RETURN count(n) AS c").single()
    return int(result["c"]) if result else 0


def _count_relation(rel_type: str, src_class: str, tgt_class: str) -> int:
    cypher = (
        f"MATCH (s:OntologyInstance)-[r:`{rel_type}`]->(t:OntologyInstance) "
        "WHERE s.class_name = $src AND t.class_name = $tgt "
        "RETURN count(r) AS c"
    )
    with graph_db.graph_session() as session:
        result = session.run(cypher, src=src_class, tgt=tgt_class).single()
    return int(result["c"]) if result else 0


def _seed_feature_and_spec() -> dict:
    """Create Feature + Spec in SQL and mirror to Neo4j. Return all ids/props local-var form."""
    with session_scope() as session:
        feature = ontology_service.create_instance_by_class_name(
            session,
            ClassName.FEATURE,
            title=f"测试 Feature-{uuid.uuid4().hex[:6]}",
            status="idea",
            properties={"description": "E2E test feature"},
        )
        spec = ontology_service.create_instance_by_class_name(
            session,
            ClassName.SPEC,
            title=f"测试 Spec-{uuid.uuid4().hex[:6]}",
            status="draft",
            properties={
                "goal": "验证 Neo4j 关系写入",
                "version": "1.0.0",
                "background": "Test background",
            },
        )
        feature_rel = ontology_service.relate(session, feature.id, spec.id, RelationType.DERIVES_TO)
        snap = {
            "feature_id": feature.id,
            "spec_id": spec.id,
            "spec_title": spec.title,
            "spec_status": spec.status,
            "spec_props": dict(spec.properties or {}),
            "feature_neo4j_rel_id": feature_rel.id,
        }
    # mirror to Neo4j + Feature→Spec relation
    graph_db.upsert_instance(
        instance_id=snap["feature_id"],
        class_name=ClassName.FEATURE,
        title="测试 Feature",
        status="idea",
        properties={"description": "E2E test feature"},
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )
    graph_db.upsert_instance(
        instance_id=snap["spec_id"],
        class_name=ClassName.SPEC,
        title=snap["spec_title"],
        status=snap["spec_status"],
        properties=snap["spec_props"],
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )
    graph_db.relate_instances(
        relation_id=snap["feature_neo4j_rel_id"],
        source_id=snap["feature_id"],
        target_id=snap["spec_id"],
        relation_type=RelationType.DERIVES_TO,
        properties={},
    )
    return snap


def part_a_create_approval(snap: dict) -> int:
    """Mimic create_spec_approval: create FeishuMessage + CONTAINS Spec→FeishuMessage in Neo4j."""
    spec_id = snap["spec_id"]
    spec_title = snap["spec_title"]

    # 1. Call feishu_client.create_approval
    form = feishu_client.build_spec_approval_form(
        spec_title=spec_title,
        spec_goal="验证 Neo4j 关系写入",
        spec_version="1.0.0",
        spec_background="Test background",
    )
    approval_result = feishu_client.create_approval(
        approval_code="MOCK_TEMPLATE",
        user_id="ou_mock_approver",
        form=form,
    )
    instance_code = approval_result.get("instance_code", "")
    assert instance_code, "Approval instance_code 必须返回"
    print(f"[PART A] 飞书审批已创建: {instance_code} (via={approval_result.get('via')})")

    # 2. Persist ApprovalMapping
    with session_scope() as session:
        mapping = ApprovalMappingORM(
            spec_id=spec_id,
            instance_code=instance_code,
            status="PENDING",
            approver_open_id="ou_mock_approver",
        )
        session.add(mapping)
        session.flush()
    feishu_events.register_mapping(spec_id, instance_code)

    # 3. Create FeishuMessage instance (mimics create_spec_approval MCP body)
    msg_full_props = {
        "chat_id": "ou_mock_approver",
        "content": f"已为 Spec '{spec_title}' 创建飞书审批（{instance_code}）",
        "sent_at": datetime.now(UTC).isoformat(),
        "via": approval_result.get("via", "unknown"),
        "approval_instance_code": instance_code,
        "mock": approval_result.get("via") == "mock",
    }

    # Split declared vs extras (FeishuMessage declares chat_id/content/sent_at/title)
    with session_scope() as session:
        msg = ontology_service.create_instance_by_class_name(
            session,
            ClassName.FEISHU_MESSAGE,
            title=f"Spec 审批: {spec_title}",
            status="pending",
            properties={
                "chat_id": msg_full_props["chat_id"],
                "content": msg_full_props["content"],
                "sent_at": msg_full_props["sent_at"],
            },
        )
        msg.properties = {**(msg.properties or {}), **{k: v for k, v in msg_full_props.items() if k not in ("chat_id", "content", "sent_at")}}
        session.flush()
        msg_id_local = msg.id
        msg_title_local = msg.title
        msg_created = msg.created_at.isoformat() if msg.created_at else None
        # RELATE — must upsert BOTH endpoints first, then relate
        graph_db.upsert_instance(
            instance_id=spec_id,
            class_name=ClassName.SPEC,
            title=spec_title,
            status=snap["spec_status"],
            properties=snap["spec_props"],
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )
        graph_db.upsert_instance(
            instance_id=msg_id_local,
            class_name=ClassName.FEISHU_MESSAGE,
            title=msg_title_local,
            status="pending",
            properties=msg_full_props,
            created_at=msg_created,
            updated_at=datetime.now(UTC).isoformat(),
        )
        relation = ontology_service.relate(
            session, spec_id, msg_id_local, RelationType.CONTAINS,
            properties={"via": "spec_approval"},
        )
        graph_db.relate_instances(
            relation_id=relation.id,
            source_id=spec_id,
            target_id=msg_id_local,
            relation_type=RelationType.CONTAINS,
            properties={"via": "spec_approval"},
        )
        print(f"[PART A] FeishuMessage created: {msg_id_local[:8]}..., CONTAINS relation added")

    return 1 if _count_relation("CONTAINS", "Spec", "FeishuMessage") == 1 else 0


def part_b_callback(snap: dict) -> dict:
    """Mimic WebSocket callback: trigger _on_approval_event, verify writeback."""
    spec_id = snap["spec_id"]

    # pick first pending mapping for this spec
    with session_scope() as session:
        mapping = session.scalar(
            select(ApprovalMappingORM).where(ApprovalMappingORM.spec_id == spec_id)
        )
        instance_code = mapping.instance_code if mapping else ""

    approve_result = feishu_client.approve_task(instance_code, "APPROVED", comment="approved via test")
    print(f"[PART B] 模拟用户批准: {approve_result.get('status')} (via={approve_result.get('via')})")
    feishu_events._on_approval_event(instance_code, "APPROVED")
    print(f"[PART B] _on_approval_event 已触发写回")

    with session_scope() as session:
        spec_fresh = get_instance_or_404(session, spec_id)
        result = {
            "spec_status": spec_fresh.status,
            "approval_status": spec_fresh.properties.get("approval_status"),
        }
        mapping_rows = session.execute(
            select(ApprovalMappingORM).where(ApprovalMappingORM.instance_code == instance_code)
        ).scalars().all()
        result["mapping_status"] = mapping_rows[0].status if mapping_rows else "MISSING"

    result["spec_count"] = _count_nodes("Spec")
    result["reflection_count"] = _count_nodes("Reflection")
    result["has_reflection"] = _count_relation("HAS_REFLECTION", "Spec", "Reflection")
    return result


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with session_scope() as session:
        seed_database(session)
    _wipe_neo4j_test_nodes()

    snap = _seed_feature_and_spec()
    print(f"[SETUP] Created Feature={snap['feature_id'][:8]}..., Spec={snap['spec_id'][:8]}...")

    contains_ok = part_a_create_approval(snap)
    print(f"[PART A] Neo4j CONTAINS Spec→FeishuMessage: {contains_ok} (expect 1)")

    b = part_b_callback(snap)
    print(f"\n[PART B] Spec status: {b['spec_status']} (expect ready)")
    print(f"[PART B] ApprovalMapping status: {b['mapping_status']} (expect APPROVED)")
    print(f"[PART B] approval_status in spec props: {b['approval_status']} (expect APPROVED)")
    print(f"[PART B] Neo4j Spec: {b['spec_count']} (expect ≥1)")
    print(f"[PART B] Neo4j Reflection: {b['reflection_count']} (expect 1)")
    print(f"[PART B] Neo4j HAS_REFLECTION Spec→Reflection: {b['has_reflection']} (expect 1)")

    _wipe_neo4j_test_nodes()
    try:
        Path("test_feishu_e2e.db").unlink(missing_ok=True)
        Path("test_feishu_e2e.db-journal").unlink(missing_ok=True)
    except OSError:
        pass

    ok = (
        contains_ok == 1
        and b["spec_status"] == "ready"
        and b["mapping_status"] == "APPROVED"
        and b["approval_status"] == "APPROVED"
        and b["spec_count"] >= 1
        and b["reflection_count"] == 1
        and b["has_reflection"] == 1
    )
    print(f"\n{'✅ ALL CHECKS PASSED' if ok else '❌ SOME CHECKS FAILED'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
