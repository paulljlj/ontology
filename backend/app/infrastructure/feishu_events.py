"""Feishu WebSocket event listener + ontology writeback.

Runs in a background daemon thread started by FastAPI's lifespan. Listens for
``approval_approval_updated_v4`` events from the Feishu Approval app; when an
approval tied to a Spec in our ontology is APPROVED or REJECTED, the
corresponding Spec instance is patched in the SQL store (and mirrored to Neo4j).

Behaviour mirrors ``ontology-agent/app/feishu_events.py``: lazy client build,
graceful degradation when ``lark_oapi.ws`` is unavailable, and a polling
fallback that supplements WebSocket if the long-lived connection drops.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.application import ontology_service
from app.domain.constants import ClassName, RelationType
from app.infrastructure.config import settings
from app.infrastructure.database import session_scope
from app.infrastructure.orm import (
    ApprovalMappingORM,
    OntologyInstanceORM,
    OntologyRelationORM,
)
from app.infrastructure import graph_db


_running = False
_in_memory_index: dict[str, str] = {}  # instance_code -> spec_id


def register_mapping(spec_id: str, instance_code: str) -> None:
    """Called by MCP tool `create_spec_approval` to persist the mapping."""
    _in_memory_index[instance_code] = spec_id


def load_persistent_mappings() -> int:
    """Re-hydrate the in-memory index from DB on startup (e.g. after restart).

    加载条件：Spec 还在 pending_review（飞书门禁开启后等待审批的状态）。
    终态（ready / draft）说明已经写回过，幂等检查会跳过；不需要再加载。
    PENDING 状态是最常见的子情况（Spec 多半也是 pending_review），独立判断只是
    减少一次 DB 查询。
    """
    try:
        from app.application.ontology_service import get_instance_or_404

        with session_scope() as session:
            rows = session.scalars(select(ApprovalMappingORM)).all()
            loaded = 0
            for row in rows:
                # 已写回过的（ready / draft）直接跳过，幂等检查会兜底
                try:
                    spec = get_instance_or_404(session, row.spec_id)
                except Exception:
                    continue
                if spec.status in ("ready", "draft"):
                    continue
                # 还在 pending_review 意味着 WS 事件还没回来，需要轮询兜底
                if spec.status == "pending_review":
                    _in_memory_index[row.instance_code] = row.spec_id
                    loaded += 1
                    continue
                # 老 Spec（没有走门禁，状态是其他值）按 PENDING 映射对待
                if row.status == "PENDING":
                    _in_memory_index[row.instance_code] = row.spec_id
                    loaded += 1
        return loaded
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[FeishuEvent] 加载历史映射失败: {exc}")
        return 0
        return 0


def _resolve_spec_id(instance_code: str) -> str | None:
    if instance_code in _in_memory_index:
        return _in_memory_index[instance_code]
    try:
        with session_scope() as session:
            row = session.scalar(
                select(ApprovalMappingORM).where(ApprovalMappingORM.instance_code == instance_code)
            )
            if row:
                _in_memory_index[instance_code] = row.spec_id
                return row.spec_id
    except Exception as exc:
        print(f"[FeishuEvent] 反查映射失败: {exc}")
    return None


def _apply_approval_result(spec_id: str, instance_code: str, status: str) -> None:
    """Patch Spec status, mirror to Neo4j, append a Reflection instance.

    SQL 和 Neo4j 必须解耦：Neo4j 写失败不能让 SQL 也回滚。
    先在 session_scope 里把所有 SQL 变更 commit 出作用域，再 try/except 包
    Neo4j upsert / relate。这样 Neo4j 容器宕掉时，本体里的 Spec/Reflection/
    HAS_REFLECTION 关系至少能落 SQL。

    幂等：如果 Spec 已经处于终态（ready / rejected）就跳过，避免重复创建 Reflection。

    拒绝时 Spec 回到 draft（不是 rejected），让用户能在本体里编辑后重新发起审批。
    通过时除了翻 ready + 写 Reflection，还会自动续跑 Plan/Task（见 _resume_workflow_after_approval）。
    """
    spec_status = "ready" if status == "APPROVED" else "draft"
    summary = (
        f"Spec 审批通过（飞书 instance_code={instance_code}）。"
        if status == "APPROVED"
        else f"Spec 审批被拒绝（飞书 instance_code={instance_code}），已回到 draft 待用户修改。"
    )

    # 幂等检查：已写过（ready / draft）的就不再写
    # draft 是"被拒后回到可编辑状态"，和 ready 一样属于终态
    try:
        with session_scope() as session:
            spec = ontology_service.get_instance_or_404(session, spec_id)
            if spec.status in ("ready", "draft"):
                # 已经写过；只确保 ApprovalMapping 状态一致
                mapping = session.scalar(
                    select(ApprovalMappingORM).where(ApprovalMappingORM.instance_code == instance_code)
                )
                if mapping and mapping.status != status:
                    mapping.status = status
                print(f"[FeishuEvent] Spec {spec_id} 已是 {spec.status}，跳过重复反写")
                return
    except Exception as exc:
        print(f"[FeishuEvent] 幂等检查失败: {exc}")
        return

    # ── Phase 1: SQL commit (Spec 状态 + Reflection + HAS_REFLECTION + ApprovalMapping 状态)
    try:
        with session_scope() as session:
            spec = ontology_service.get_instance_or_404(session, spec_id)
            old_status = spec.status
            spec.status = spec_status
            spec.properties = {
                **(spec.properties or {}),
                "approval_instance_code": instance_code,
                "approval_status": status,
                "approval_decided_at": datetime.now(UTC).isoformat(),
            }
            session.flush()

            reflection = ontology_service.create_instance_by_class_name(
                session,
                ClassName.REFLECTION,
                title=f"Spec 审批结果: {status}",
                status="info",
                properties={
                    "summary": summary,
                    "failed_checks": [] if status == "APPROVED" else ["approval_rejected"],
                },
            )
            relation = ontology_service.relate(
                session, spec_id, reflection.id, RelationType.HAS_REFLECTION,
            )

            mapping = session.scalar(
                select(ApprovalMappingORM).where(ApprovalMappingORM.instance_code == instance_code)
            )
            if mapping:
                mapping.status = status

            session.flush()
            # 快照要在 session 关闭前拷出来
            snap = {
                "spec_id": spec.id,
                "spec_title": spec.title,
                "spec_props": dict(spec.properties or {}),
                "spec_created": spec.created_at.isoformat() if spec.created_at else None,
                "reflection_id": reflection.id,
                "reflection_title": reflection.title,
                "reflection_props": dict(reflection.properties or {}),
                "reflection_created": reflection.created_at.isoformat() if reflection.created_at else None,
                "relation_id": relation.id,
                "old_status": old_status,
            }
        # session_scope 退出，SQL 已 commit
        print(f"[FeishuEvent] Spec {snap['spec_id']} {snap['old_status']} → {spec_status}")
    except Exception as exc:
        print(f"[FeishuEvent] SQL 反写失败: {exc}")
        return

    # ── Phase 2: Neo4j 镜像（独立 try/except，失败不影响 SQL）
    try:
        now = datetime.now(UTC).isoformat()
        graph_db.upsert_instance(
            instance_id=snap["spec_id"],
            class_name=ClassName.SPEC,
            title=snap["spec_title"],
            status=spec_status,
            properties=snap["spec_props"],
            created_at=snap["spec_created"],
            updated_at=now,
        )
        graph_db.upsert_instance(
            instance_id=snap["reflection_id"],
            class_name=ClassName.REFLECTION,
            title=snap["reflection_title"],
            status="info",
            properties=snap["reflection_props"],
            created_at=snap["reflection_created"],
            updated_at=now,
        )
        graph_db.relate_instances(
            relation_id=snap["relation_id"],
            source_id=snap["spec_id"],
            target_id=snap["reflection_id"],
            relation_type=RelationType.HAS_REFLECTION,
            properties={},
        )
    except Exception as exc:
        # Neo4j 失败不阻断；下次重跑（如服务重启 + 重发事件）会补上
        print(f"[FeishuEvent] Neo4j 镜像失败（SQL 已生效）: {exc}")

    # ── Phase 3: 自动续跑下游（仅通过时）
    # Spec 翻成 ready 之后，自动调 Plan + Task 生成，不需要用户回前端再点
    if status == "APPROVED":
        _resume_workflow_after_approval(spec_id)


def _resume_workflow_after_approval(spec_id: str) -> None:
    """审批通过后自动续跑 Plan + Tasks。

    顺着 DERIVES_TO 反查父 Feature（理论上 Spec 一定由 Feature 派生），
    调 generate_plan_from_spec 和 generate_tasks_from_plan。
    失败不阻断主流程，用户可手动再点 plan/tasks 按钮。
    """
    from app.application.workflows import generate_plan_from_spec, generate_tasks_from_plan

    try:
        with session_scope() as session:
            parent_feature_id = session.scalar(
                select(OntologyRelationORM.source_id).where(
                    OntologyRelationORM.target_id == spec_id,
                    OntologyRelationORM.type == RelationType.DERIVES_TO,
                )
            )
            if not parent_feature_id:
                print(f"[FeishuEvent] Spec {spec_id} 找不到父 Feature，跳过自动续跑")
                return
            # 续跑前再确认一次状态（防止并发事件或重投递把 Spec 弄回 draft）
            spec = ontology_service.get_instance_or_404(session, spec_id)
            if spec.status != "ready":
                print(f"[FeishuEvent] Spec {spec_id} 当前 {spec.status}，跳过自动续跑")
                return
            plan_result = generate_plan_from_spec(session, spec_id)
            generate_tasks_from_plan(session, plan_result["plan"].id)
        print(f"[FeishuEvent] Spec {spec_id} 审批通过，Plan + Tasks 自动续跑完成")
    except Exception as exc:
        # 续跑失败不影响主流程；用户可手动再点 plan/tasks
        print(f"[FeishuEvent] 审批后续跑失败: {exc}")


def _on_approval_event(instance_code: str, raw_status: str) -> None:
    """Common entry point for both WebSocket and polling callbacks."""
    if not instance_code:
        print("[FeishuEvent] 收到审批事件但缺少 instance_code")
        return
    spec_id = _resolve_spec_id(instance_code)
    if not spec_id:
        print(f"[FeishuEvent] 未找到 instance_code 对应的 Spec: {instance_code}")
        return
    normalised = raw_status.upper()
    if normalised == "APPROVED":
        _apply_approval_result(spec_id, instance_code, "APPROVED")
    elif normalised in ("REJECTED", "CANCELED", "CANCELLED"):
        _apply_approval_result(spec_id, instance_code, "REJECTED")
    else:
        print(f"[FeishuEvent] 忽略状态: {raw_status} (instance: {instance_code})")


def reconcile_neo4j_mirror() -> int:
    """Backfill any Spec → Reflection relations missing from Neo4j.

    Catches the case where a writeback committed SQL but the Neo4j mirror
    failed (e.g. container down at the time). Idempotent: re-runs are safe.
    Returns the number of edges reconciled.
    """
    try:
        # 在 session 内把所有要用的 ORM 字段快照成纯值，避免 session 关闭后
        # 访问 detached 实例触发 DetachedInstanceError。
        snapshots: list[dict[str, Any]] = []
        with session_scope() as session:
            spec_edges = session.execute(
                select(
                    OntologyRelationORM.id,
                    OntologyRelationORM.source_id,
                    OntologyRelationORM.target_id,
                    OntologyRelationORM.properties,
                ).where(OntologyRelationORM.type == RelationType.HAS_REFLECTION)
            ).all()
            if not spec_edges:
                return 0
            ids = {row[1] for row in spec_edges} | {row[2] for row in spec_edges}
            instances = session.scalars(
                select(OntologyInstanceORM)
                .options(joinedload(OntologyInstanceORM.ontology_class))
                .where(OntologyInstanceORM.id.in_(ids))
            ).all()
            by_id = {inst.id: inst for inst in instances}
            for relation_id, source_id, target_id, props in spec_edges:
                source = by_id.get(source_id)
                target = by_id.get(target_id)
                if not source or not target:
                    continue
                snapshots.append({
                    "relation_id": relation_id,
                    "source_id": source_id,
                    "target_id": target_id,
                    "relation_props": dict(props or {}),
                    "source": {
                        "id": source.id,
                        "title": source.title,
                        "status": source.status,
                        "properties": dict(source.properties or {}),
                        "created_at": source.created_at.isoformat() if source.created_at else None,
                    },
                    "target": {
                        "id": target.id,
                        "title": target.title,
                        "status": target.status,
                        "properties": dict(target.properties or {}),
                        "created_at": target.created_at.isoformat() if target.created_at else None,
                    },
                })
        # session 已关闭，安全地驱动 Neo4j 写
        reconciled = 0
        for snap in snapshots:
            try:
                now = datetime.now(UTC).isoformat()
                graph_db.upsert_instance(
                    instance_id=snap["source"]["id"],
                    class_name=ClassName.SPEC,
                    title=snap["source"]["title"],
                    status=snap["source"]["status"],
                    properties=snap["source"]["properties"],
                    created_at=snap["source"]["created_at"],
                    updated_at=now,
                )
                graph_db.upsert_instance(
                    instance_id=snap["target"]["id"],
                    class_name=ClassName.REFLECTION,
                    title=snap["target"]["title"],
                    status=snap["target"]["status"],
                    properties=snap["target"]["properties"],
                    created_at=snap["target"]["created_at"],
                    updated_at=now,
                )
                graph_db.relate_instances(
                    relation_id=snap["relation_id"],
                    source_id=snap["source_id"],
                    target_id=snap["target_id"],
                    relation_type=RelationType.HAS_REFLECTION,
                    properties=snap["relation_props"],
                )
                reconciled += 1
            except Exception as exc:
                print(f"[FeishuEvent] 镜像 {snap['source_id']} → {snap['target_id']} 失败: {exc}")
        if reconciled:
            print(f"[FeishuEvent] Neo4j 镜像补齐 {reconciled} 条 HAS_REFLECTION 关系")
        return reconciled
    except Exception as exc:  # pragma: no cover
        print(f"[FeishuEvent] Neo4j 镜像对账失败: {exc}")
        return 0


def start_event_listener() -> None:
    """Spawn the background WebSocket thread. Idempotent — safe to call repeatedly."""
    global _running
    if _running:
        return
    if not settings.feishu_event_enabled:
        print("[FeishuEvent] 飞书事件监听已禁用 (feishu_event_enabled=false)")
        return
    if not settings.feishu_enabled:
        print("[FeishuEvent] 未配置飞书凭证，跳过 WebSocket 监听（Spec 状态需手动或轮询更新）")
        return

    _running = True
    load_persistent_mappings()
    reconcile_neo4j_mirror()

    thread = threading.Thread(target=_run_listener, daemon=True, name="feishu-event-listener")
    thread.start()


def _run_listener() -> None:
    """Try WebSocket first; on any failure, fall back to polling."""
    # ── Polling fallback always runs in parallel — WS can be connected but still miss
    # events (e.g. custom App not deployed yet, or delivery method misconfigured).
    polling_thread = threading.Thread(target=_poll_loop, daemon=True, name="feishu-polling")
    polling_thread.start()

    try:
        from lark_oapi import EventDispatcherHandler, LogLevel
        from lark_oapi.ws import Client as WSClient

        def _handle(data: Any) -> None:
            """lark-oapi passes ``P2ApprovalApprovalUpdatedV4`` whose ``event.object``
            is an ``ApprovalEvent`` model. The actual instance_code / status live
            inside ``process_obj``, a JSON string that has to be parsed manually.
            """
            try:
                event_obj = getattr(getattr(data, "event", None), "object", None)
                if event_obj is None:
                    print(f"[FeishuEvent] 事件结构无 event.object: {data!r}")
                    return
                process_json = getattr(event_obj, "process_obj", "") or ""
                process = json.loads(process_json) if process_json else {}
                instance_code = process.get("instance_code", "")
                raw_status = process.get("status", "")
            except (json.JSONDecodeError, TypeError, AttributeError) as exc:
                print(f"[FeishuEvent] 解析事件失败: {exc}; data={data!r}")
                return
            print(f"[FeishuEvent] 收到事件: instance={instance_code} status={raw_status}")
            _on_approval_event(instance_code, raw_status)

        handler = EventDispatcherHandler.builder(
            settings.feishu_app_id, settings.feishu_app_secret
        ).register_p2_approval_approval_updated_v4(_handle).build()

        client = WSClient(
            settings.feishu_app_id,
            settings.feishu_app_secret,
            event_handler=handler,
            log_level=LogLevel.INFO,
        )
        print("[FeishuEvent] WebSocket 长连接已启动")
        client.start()
    except ImportError:
        print("[FeishuEvent] lark_oapi.ws 不可用，跳过 WebSocket 监听")
    except Exception as exc:
        print(f"[FeishuEvent] WebSocket 启动失败: {exc}")
        # Polling thread continues regardless


def _poll_loop() -> None:
    """Periodically pull approval status via REST API — backs up the WebSocket.

    Runs in parallel with the WS so events missed by the WS (custom App not yet
    deployed, misconfigured delivery method, transient WS drop) are still caught.
    """
    from app.infrastructure import feishu_client

    print("[FeishuEvent] 轮询已启动（10s 间隔，与 WebSocket 并行）")
    seen_status: dict[str, str] = {}

    # 启动时主动同步一次：把所有 mapping 当作"之前是 PENDING"看待，
    # 第一次 poll 就能发现已经 APPROVED/REJECTED 但还未反写的审批（典型场景：
    # 后端重启后用户已经点过同意，但 WS 没收到事件或重启错过了）。
    for instance_code in list(_in_memory_index.keys()):
        seen_status[instance_code] = "PENDING"

    while True:
        time.sleep(10)
        for instance_code, spec_id in list(_in_memory_index.items()):
            try:
                result = feishu_client.get_approval_status(instance_code)
                raw = result.get("raw_status") or result.get("status")
                if not raw or raw == seen_status.get(instance_code):
                    continue
                seen_status[instance_code] = raw
                print(f"[FeishuEvent] 轮询发现状态变化: {instance_code} → {raw}")
                if raw in ("APPROVED", "REJECTED", "CANCELED", "CANCELLED"):
                    _on_approval_event(instance_code, raw)
            except Exception as exc:  # pragma: no cover
                print(f"[FeishuEvent] 轮询失败: {exc}")
