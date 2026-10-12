# 导入高精度计时器，用来统计函数执行耗时，配合日志装饰器使用
from time import perf_counter

# FastAPI 标准异常，用来返回 409 (门禁未通过) / 502 (飞书调用失败)
from fastapi import HTTPException

# SQLAlchemy 2.0 核心语法：构造SELECT查询语句
from sqlalchemy import select
# Session：数据库会话，所有数据库读写操作都依靠会话执行
# joinedload：预加载关联数据，避免查询本体关联关系时产生N+1性能问题
from sqlalchemy.orm import Session, joinedload

# 从应用服务层导入本体操作工具函数（DDD application层，编排业务逻辑）
from app.application.ontology_service import (
    create_instance_by_class_name,  # 根据本体类型名称，创建一条本体实例存入数据库
    get_instance_or_404,            # 根据ID查询本体实例，找不到直接抛出404异常（接口专用）
    log_execution,                  # 装饰器：自动记录函数开始、结束、执行耗时
    read_instance,                  # 将数据库ORM对象 → 转换成对外传输的Pydantic模型 OntologyInstanceRead
    relate,                         # 建立两个本体实例之间的语义关联（写入关系表）
)

# 领域层常量：统一存放业务枚举，避免代码里手写字符串引发拼写错误
from app.domain.constants import ClassName, RelationType
# 领域层数据模型：Pydantic读取模型，承载本体实例对外展示/传输的数据
# 也就是AIProvider三个方法接收的入参类型 OntologyInstanceRead
from app.domain.schemas import OntologyInstanceRead

# 基础设施层：导入全局AI工具实例（RuleBasedAIProvider 或 LLMProvider）
from app.infrastructure.ai_provider import ai_provider
# 基础设施层：全局配置（feishu_enabled / approval_code 等）
from app.infrastructure.config import settings

# 基础设施层ORM模型：SQLAlchemy数据库映射类，对应三张数据表
from app.infrastructure.orm import (
    ApprovalMappingORM,
    OntologyClassORM,
    OntologyInstanceORM,
    OntologyRelationORM,
)


def _extract_title_body(item_data, default_title_prefix: str = "Item") -> tuple[str, str]:
    """
    兼容两种 LLM 输出格式：
    - dict: {"title": "...", "body": "..."}  → 返回 ("title", "body")
    - str:  "some text"                        → 返回 ("{prefix}: text", "text")
    """
    if isinstance(item_data, dict):
        title_text = item_data.get("title") or item_data.get("name") or f"{default_title_prefix}"
        body_text = item_data.get("body") or item_data.get("description") or item_data.get("content") or title_text
        return str(title_text), str(body_text)
    text = str(item_data)
    return f"{default_title_prefix}: {text[:60]}", text

def _duration_ms(start: float) -> int:
    return int((perf_counter() - start) * 1000)


def generate_spec_from_feature(
    session: Session,
    feature_id: str,
    require_feishu_approval: bool = False,
) -> dict:
    """根据 Feature 生成 Spec。可选开启飞书审批门禁。

    - 默认 (require_feishu_approval=False)：Spec 一步到位到 ready，下游 Plan/Task 可以直接生成
    - 开启 (require_feishu_approval=True)：Spec 停在 pending_review，调用飞书创建审批实例；
      用户在飞书 App 点同意后由 feishu_events._apply_approval_result 自动续跑 Plan/Task
    """
    start = perf_counter()
    feature = get_instance_or_404(session, feature_id)
    data = ai_provider.generate_spec(read_instance(feature))

    # 门禁开启时 Spec 停在 pending_review，关闭时直接 ready
    spec_status = "pending_review" if require_feishu_approval else "ready"
    spec = create_instance_by_class_name(
        session,
        ClassName.SPEC,
        data["title"],
        spec_status,
        {"goal": data["goal"], "ai_provider": "llm" if hasattr(ai_provider, '__class__') and ai_provider.__class__.__name__ == "LLMProvider" else "rule-based"},
    )
    relate(session, feature.id, spec.id, RelationType.DERIVES_TO)

    stories = []
    for story_data in data["stories"]:
        story = create_instance_by_class_name(
            session,
            ClassName.USER_STORY,
            story_data["title"],
            "ready",
            {"body": story_data["body"]},
        )
        relate(session, spec.id, story.id, RelationType.HAS_STORY)
        stories.append(read_instance(story))

    acceptances = []
    for index, text in enumerate(data["acceptance"], start=1):
        acceptance = create_instance_by_class_name(
            session,
            ClassName.ACCEPTANCE,
            f"AC-{index}: {text}",
            "ready",
            {"rule": text},
        )
        relate(session, spec.id, acceptance.id, RelationType.HAS_ACCEPTANCE)
        acceptances.append(read_instance(acceptance))

    for text in data["clarifications"]:
        clarification = create_instance_by_class_name(
            session,
            ClassName.CLARIFICATION,
            text,
            "open",
            {"question": text},
        )
        relate(session, spec.id, clarification.id, RelationType.CONTAINS)

    # ── 飞书审批门禁：调用飞书建审批实例，把 mapping 落库 + 注册到内存索引
    #    失败时 Spec 翻回 draft，让用户能编辑后重发
    if require_feishu_approval and settings.feishu_enabled:
        from app.infrastructure import feishu_client, feishu_events

        spec_props = dict(spec.properties or {})
        form = feishu_client.build_spec_approval_form(
            spec_title=spec.title,
            spec_goal=spec_props.get("goal", ""),
            spec_version=spec_props.get("version", ""),
            spec_background=spec_props.get("background", ""),
        )
        approval = feishu_client.create_approval(
            approval_code=settings.feishu_approval_code or "MOCK_TEMPLATE",
            user_id=settings.feishu_default_approver or "ou_mock_approver",
            form=form,
        )
        if approval.get("status") == "ok":
            mapping = ApprovalMappingORM(
                spec_id=spec.id,
                instance_code=approval.get("instance_code", ""),
                status="PENDING",
                approver_open_id=settings.feishu_default_approver or "",
            )
            session.add(mapping)
            session.flush()
            # 注册到内存索引，让 WebSocket / 轮询能反查到 spec_id
            feishu_events.register_mapping(spec.id, approval.get("instance_code", ""))
        else:
            # 飞书调用失败：Spec 翻回 draft + 抛 502，前端会提示"审批发起失败"
            spec.status = "draft"
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "飞书审批发起失败，Spec 已回到 draft，请稍后重试",
                    "approval": approval,
                },
            )

    log = log_execution(
        session,
        "generate_spec_from_feature",
        feature.id,
        "success",
        _duration_ms(start),
        f"Generated {len(stories)} stories and {len(acceptances)} acceptance criteria.",
    )
    relate(session, feature.id, log.id, RelationType.CONTAINS)
    return {"spec": read_instance(spec), "stories": stories, "acceptance": acceptances}


def generate_plan_from_spec(session: Session, spec_id: str) -> dict:
    start = perf_counter()
    spec = get_instance_or_404(session, spec_id)
    # 门禁守卫：Spec 等待飞书审批时拒绝生成 Plan
    if spec.status == "pending_review":
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Spec 等待飞书审批通过，请稍后重试",
                "spec_status": "pending_review",
            },
        )
    data = ai_provider.generate_plan(read_instance(spec))

    plan = create_instance_by_class_name(
        session,
        ClassName.PLAN,
        data["title"],
        "ready",
        {"summary": data["summary"], "architecture": "DDD layered MVP"},
    )
    relate(session, spec.id, plan.id, RelationType.HAS_PLAN)

    data_models = []
    for item_data in data["data_models"]:
        title_text, body_text = _extract_title_body(item_data, default_title_prefix="DataModel")
        item = create_instance_by_class_name(session, ClassName.DATA_MODEL, title_text, "ready", {"body": body_text})
        relate(session, plan.id, item.id, RelationType.CONTAINS)
        data_models.append(read_instance(item))

    contracts = []
    for item_data in data["contracts"]:
        title_text, body_text = _extract_title_body(item_data, default_title_prefix="Contract")
        item = create_instance_by_class_name(session, ClassName.CONTRACT, title_text, "ready", {"body": body_text})
        relate(session, plan.id, item.id, RelationType.CONTAINS)
        contracts.append(read_instance(item))

    adrs = []
    for item_data in data["adrs"]:
        if isinstance(item_data, dict):
            title_text = item_data.get("title") or f"ADR: {item_data.get('decision', '')[:30]}"
            decision_text = item_data.get("decision", "")
        else:
            title_text = f"ADR: {str(item_data)[:40]}"
            decision_text = str(item_data)
        item = create_instance_by_class_name(session, ClassName.ADR, title_text, "accepted", {"decision": decision_text})
        relate(session, plan.id, item.id, RelationType.CONTAINS)
        adrs.append(read_instance(item))

    log = log_execution(
        session,
        "generate_plan_from_spec",
        spec.id,
        "success",
        _duration_ms(start),
        "Generated plan with data models, contracts, and ADRs.",
    )
    relate(session, spec.id, log.id, RelationType.CONTAINS)
    return {"plan": read_instance(plan), "data_models": data_models, "contracts": contracts, "adrs": adrs}


def generate_tasks_from_plan(session: Session, plan_id: str) -> dict:
    start = perf_counter()
    plan = get_instance_or_404(session, plan_id)
    # 门禁守卫：顺着 HAS_PLAN 反查 Spec，若 Spec 仍 pending_review 拒绝生成 Task
    spec_id = session.scalar(
        select(OntologyRelationORM.source_id).where(
            OntologyRelationORM.target_id == plan_id,
            OntologyRelationORM.type == RelationType.HAS_PLAN,
        )
    )
    if spec_id:
        spec = session.get(OntologyInstanceORM, spec_id)
        if spec and spec.status == "pending_review":
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Spec 等待飞书审批通过，请稍后重试",
                    "spec_status": "pending_review",
                },
            )
    task_data = ai_provider.generate_tasks(read_instance(plan))
    tasks = []
    for index, item in enumerate(task_data, start=1):
        layer = item.get("layer", "application")
        dod = item.get("definition_of_done", [])
        task = create_instance_by_class_name(
            session,
            ClassName.TASK,
            f"T{index:02d} {item['title']}",
            "todo",
            {
                "layer": layer,
                "definition_of_done": dod,
            },
        )
        relate(session, plan.id, task.id, RelationType.HAS_TASK)
        tasks.append(read_instance(task))
    log = log_execution(
        session,
        "generate_tasks_from_plan",
        plan.id,
        "success",
        _duration_ms(start),
        f"Generated {len(tasks)} DDD-layered tasks.",
    )
    relate(session, plan.id, log.id, RelationType.CONTAINS)
    return {"tasks": tasks}


def run_checklist(session: Session, root_id: str) -> dict:
    start = perf_counter()
    root = get_instance_or_404(session, root_id)
    graph_edges = session.scalars(select(OntologyRelationORM)).all()
    outgoing = [edge for edge in graph_edges if edge.source_id == root.id]
    target_ids = {edge.target_id for edge in outgoing}
    targets = session.scalars(
        select(OntologyInstanceORM)
        .options(joinedload(OntologyInstanceORM.ontology_class))
        .where(OntologyInstanceORM.id.in_(target_ids))
    ).all()
    target_classes = {target.ontology_class.name for target in targets}

    checks = []
    if root.ontology_class.name == ClassName.FEATURE:
        checks.append(("Feature has Spec", ClassName.SPEC in target_classes))
        spec_ids = [target.id for target in targets if target.ontology_class.name == ClassName.SPEC]
        plan_found = False
        task_found = False
        for spec_id in spec_ids:
            plan_edges = [edge for edge in graph_edges if edge.source_id == spec_id]
            plan_target_ids = {edge.target_id for edge in plan_edges}
            plan_targets = session.scalars(
                select(OntologyInstanceORM)
                .options(joinedload(OntologyInstanceORM.ontology_class))
                .where(OntologyInstanceORM.id.in_(plan_target_ids))
            ).all()
            plan_ids = [target.id for target in plan_targets if target.ontology_class.name == ClassName.PLAN]
            plan_found = plan_found or bool(plan_ids)
            for plan_id in plan_ids:
                task_edges = [edge for edge in graph_edges if edge.source_id == plan_id]
                task_target_ids = {edge.target_id for edge in task_edges}
                task_targets = session.scalars(
                    select(OntologyInstanceORM)
                    .options(joinedload(OntologyInstanceORM.ontology_class))
                    .where(OntologyInstanceORM.id.in_(task_target_ids))
                ).all()
                task_found = task_found or any(
                    target.ontology_class.name == ClassName.TASK for target in task_targets
                )
        checks.append(("Spec has Plan", plan_found))
        checks.append(("Plan has Task", task_found))
    else:
        checks.append(("Instance has title", bool(root.title.strip())))
        checks.append(("Instance has properties", bool(root.properties)))

    passed = [name for name, ok in checks if ok]
    failed = [name for name, ok in checks if not ok]
    status = "passed" if not failed else "failed"
    checklist = create_instance_by_class_name(
        session,
        ClassName.CHECKLIST,
        f"Checklist for {root.title}",
        status,
        {"passed": passed, "failed": failed, "checks": [{"name": name, "ok": ok} for name, ok in checks]},
    )
    relate(session, root.id, checklist.id, RelationType.HAS_CHECKLIST)
    reflection = create_instance_by_class_name(
        session,
        ClassName.REFLECTION,
        f"Reflection for {root.title}",
        "ready",
        {
            "summary": "当前拓扑可进入下一步。" if not failed else "当前拓扑仍有缺口，需要补齐失败检查项。",
            "failed_checks": failed,
        },
    )
    relate(session, root.id, reflection.id, RelationType.HAS_REFLECTION)
    log = log_execution(
        session,
        "run_checklist",
        root.id,
        status,
        _duration_ms(start),
        f"Checklist completed with {len(passed)} passed and {len(failed)} failed.",
    )
    relate(session, root.id, log.id, RelationType.CONTAINS)
    return {"checklist": read_instance(checklist), "reflection": read_instance(reflection)}
