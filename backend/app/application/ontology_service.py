from collections import deque
# 导入双端队列，用于 BFS 广度优先遍历，get_graph图谱查询用

from datetime import datetime
from typing import Any

from fastapi import HTTPException
# FastAPI标准异常，接口返回404/400等HTTP错误

from sqlalchemy import or_, select
# select：SQLAlchemy2.0查询构造器
# or_：SQL或条件拼接

from sqlalchemy.orm import Session, joinedload
# Session：数据库会话
# joinedload：主动预加载关联对象，解决N+1查询问题

from app.domain import reasoner
from app.domain.schemas import (
    GraphRead,               # 图谱整体返回DTO（节点+边）
    InstanceCreate,          # 创建实例请求模型
    InstancePatch,           # 修改实例请求模型
    OntologyInstanceRead,    # 实例对外返回模型
    OntologyRelationRead,    # 关系对外返回模型
    RelationCreate,          # 创建关系请求模型
)

from app.infrastructure.orm import OntologyClassORM, OntologyInstanceORM, OntologyRelationORM
# 导入三张ORM数据表模型：本体类、本体实例、实例关系


def split_declared_and_extra(
    class_name: str,
    properties: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Partition ``properties`` into OWL-declared fields (validated) and runtime extras.

    Some callers (frontend composer, MCP Feishu tools) attach transport metadata
    like ``created_via`` / ``mock`` / ``message_id`` / ``approval_instance_code``
    that the ontology validator rejects. We let declared fields through the
    validator, and stash the rest in the same JSON column so callers can still
    read them back without losing data.
    """
    from app.domain import ontology

    if not properties:
        return {}, {}
    schema = ontology.get_schema(class_name)
    declared = set(schema.get("fields", {}).keys()) | {"title", "status"}
    core = {k: v for k, v in properties.items() if k in declared}
    extras = {k: v for k, v in properties.items() if k not in declared}
    return core, extras


# 定义转换函数：把数据库ORM实体对象 → 接口对外返回的Pydantic模型
def read_instance(instance: OntologyInstanceORM) -> OntologyInstanceRead:
    # 实例化对外输出DTO OntologyInstanceRead，填充各个字段
    return OntologyInstanceRead(
        id=instance.id,                      # 实例唯一主键ID，取自ORM主键
        class_id=instance.class_id,          # 归属本体类外键ID
        class_name=instance.ontology_class.name, 
        # ontology_class是ORM relationship关联对象；取出本体类名称（如PROJECT、FEATURE）
        # 前端不需要再联表查询，直接拿到类型名字
        title=instance.title,                # 实例标题
        status=instance.status,              # 实例生命周期状态
        properties=instance.properties or {},
        # properties可能从数据库读出为NULL，用or {}兜底，保证对外永远返回字典，避免前端解析报错
        created_at=instance.created_at,      # 创建时间
        updated_at=instance.updated_at,      # 更新时间
    )


# 定义转换函数：将数据库关系ORM实体 → 对外输出DTO
def read_relation(relation: OntologyRelationORM) -> OntologyRelationRead:
    # model_validate：Pydantic提供的静态方法
    # 从relation对象中自动读取属性，构造OntologyRelationRead实例
    return OntologyRelationRead.model_validate(relation)
    # from_attributes=True 是前提，model_validate() 才能从 ORM 对象转换。


# 根据本体类名称查询 OntologyClassORM，找不到直接抛出404
def get_class_by_name(session: Session, name: str) -> OntologyClassORM:
    # 构造查询语句：查询 OntologyClassORM，条件 name = 传入参数name
    ontology_class = session.scalar(select(OntologyClassORM).where(OntologyClassORM.name == name))
    # scalar：执行SQL，返回第一条匹配记录；无结果返回 None

    # 判断查询结果，如果为空（没找到对应的本体类）
    if not ontology_class:
        # 抛出FastAPI HTTP异常，接口会直接返回前端 404
        raise HTTPException(status_code=404, detail=f"Ontology class not found: {name}")
    # 查询成功，返回本体类ORM对象
    return ontology_class


def get_instance_or_404(session: Session, instance_id: str) -> OntologyInstanceORM:
    # 根据实例ID查询实例，同时预加载关联的本体类信息
    instance = session.scalar(
        select(OntologyInstanceORM)
        .options(joinedload(OntologyInstanceORM.ontology_class)) # 预加载关联本体类，防止N+1查询
        .where(OntologyInstanceORM.id == instance_id)             # 根据实例主键筛选
    )
    # 未查询到实例，抛出404接口异常
    if not instance:
        raise HTTPException(status_code=404, detail=f"Instance not found: {instance_id}")
    # 返回查询到的实例ORM对象
    return instance

# 各种筛选条件，从数据库里查询实例列表，并返回给前端。
def list_instances(
    session: Session,
    class_name: str | None = None,    # 按本体类名称筛选（可选） 不说就是所有
    q: str | None = None,             # 模糊搜索关键词（可选）
    status: str | None = None,        # 按实例状态筛选（可选）
) -> list[OntologyInstanceRead]:
    # 基础查询：查询实例，预加载关联本体类，防止N+1查询
    stmt = select(OntologyInstanceORM).options(joinedload(OntologyInstanceORM.ontology_class))
    # 如果指定类别名称，联表过滤对应类的实例
    if class_name:
        stmt = stmt.join(OntologyClassORM).where(OntologyClassORM.name == class_name)
    # 如果指定状态，增加状态筛选条件
    if status:
        stmt = stmt.where(OntologyInstanceORM.status == status)
    # 如果传入搜索关键词，开启标题/状态模糊查询
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_( # 以下内容满足任意一个都行
                OntologyInstanceORM.title.ilike(pattern),   # 标题包含关键词
                OntologyInstanceORM.status.ilike(pattern),  # 状态包含关键词
            )
        )
    # 设置排序：更新时间倒序，其次创建时间倒序 
    stmt = stmt.order_by(
        OntologyInstanceORM.updated_at.desc(),   # 更新时间最新的排前面
        OntologyInstanceORM.created_at.desc()    # 创建时间最新的排前面
        )
    # 执行查询，ORM列表批量转换为对外输出DTO列表
    return [read_instance(instance) for instance in session.scalars(stmt).all()]
    # session.scalars(stmt).all()：执行查询，返回所有 ORM 对象列表
    # read_instance(instance)：把 ORM 对象转换成 Pydantic 模型


def create_instance(session: Session, payload: InstanceCreate) -> OntologyInstanceORM:
    # 根据前端传入class_id查询对应的本体类  # payload：前端传来的数据（已通过 Pydantic 验证）
    ontology_class = session.get(OntologyClassORM, payload.class_id)
    # 校验：不存在该本体类则抛出404，禁止创建实例
    if not ontology_class:
        raise HTTPException(status_code=404, detail=f"Class not found: {payload.class_id}")

    # 把 properties 拆成本体声明字段 + 运行时 extras，避免前端 / MCP 带的元数据被拒
    declared_props, extras = split_declared_and_extra(ontology_class.name, payload.properties)

    validation = reasoner.validate_instance(
        ontology_class.name,
        payload.title,
        payload.status,
        declared_props,
    )
    if not validation.ok:
        raise HTTPException(status_code=422, detail={"message": "本体实例校验失败", "errors": validation.errors})

    # 合并：声明字段已通过校验，extras 直接落 JSON 列保留下来
    merged_props = {**(declared_props or {}), **(extras or {})}

    # 使用请求DTO字段组装数据库ORM实例
    instance = OntologyInstanceORM(
        class_id=payload.class_id,
        title=payload.title,
        status=payload.status,
        properties=merged_props,
    )
    # 将实例加入会话托管
    session.add(instance)
    # 预执行SQL，拿到生成的id，不提交事务
    session.flush()
    # 刷新实例，预加载ontology_class关联对象，否则出现N+1
    session.refresh(instance, attribute_names=["ontology_class"])
    # 返回新建完成的实例ORM
    return instance


def patch_instance(session: Session, instance_id: str, payload: InstancePatch) -> OntologyInstanceORM:
    """
    增量更新本体实例(PATCH 局部更新逻辑）
    :param session: SQLAlchemy 数据库会话
    :param instance_id: 需要更新的实例唯一标识
    :param payload: 前端传入的更新载荷,Pydantic模型,仅包含要修改的字段
    :return: 更新完成后的实例ORM对象
    """
    # 根据实例ID查询数据，不存在则直接抛出404异常
    instance = get_instance_or_404(session, instance_id)
    # 如果前端传入title字段，则更新标题；不传则保留原有值
    if payload.title is not None:
        instance.title = payload.title
    # 如果前端传入status字段，则更新状态；不传则保留原有值
    if payload.status is not None:
        instance.status = payload.status
    # 如果前端传入properties自定义属性，则覆盖更新；不传则保留原有值
    if payload.properties is not None:
        instance.properties = payload.properties
    # 将session内的变更刷新到数据库，执行UPDATE SQL，但不提交事务
    session.flush()
    # 再次查询数据库，获取最新实例快照并返回
    return get_instance_or_404(session, instance_id)


def create_relation(session: Session, payload: RelationCreate) -> OntologyRelationORM:
    """
    创建本体实例之间的关联关系
    :param session: SQLAlchemy 数据库会话对象
    :param payload: 前端提交的创建关系请求体(Pydantic模型)
    :return: 新建(或已存在)的关联ORM实体
    """
    # 根据source_id查询源实例
    source = session.get(OntologyInstanceORM, payload.source_id)
    # 根据target_id查询目标实例
    target = session.get(OntologyInstanceORM, payload.target_id)

    # 校验源实例、目标实例是否存在，任意一个不存在抛出404异常
    if not source or not target:
        raise HTTPException(status_code=404, detail="Source or target instance not found")
    validation = reasoner.validate_relation(
        payload.type,
        source.ontology_class.name,
        target.ontology_class.name,
    )
    if not validation.ok:
        raise HTTPException(status_code=422, detail={"message": "本体关系校验失败", "errors": validation.errors})

    # 构造查询语句：查询同源、同目标、同类型的关系是否已经存在
    existing = session.scalar(
        select(OntologyRelationORM).where(
            OntologyRelationORM.source_id == payload.source_id,   # 源ID匹配
            OntologyRelationORM.target_id == payload.target_id,   # 目标ID匹配
            OntologyRelationORM.type == payload.type,             # 关系类型匹配
        )
    )
    # 如果找到相同关系，直接返回已有关系，不重复创建
    if existing:
        return existing
    # 实例化新的关系ORM对象，填充字段
    relation = OntologyRelationORM(
        source_id=payload.source_id,
        target_id=payload.target_id,
        type=payload.type,
        properties=payload.properties,
    )
    # 将新建的关系加入会话，标记待插入
    session.add(relation)
    # 刷新会话，执行INSERT SQL写入数据库，但不提交事务
    session.flush()
    # 返回新建好的关系实体
    return relation


def create_instance_by_class_name(
    session: Session,                # 数据库会话，用来查库、写库
    class_name: str,                 # 用户传入：本体类的名称（例如"水泵"）
    title: str,                      # 新建实例的名称
    status: str = "draft",           # 状态，不给值默认草稿draft
    properties: dict | None = None,  # 自定义属性，可以传字典，也可以传None
) -> OntologyInstanceORM:           # 执行完返回创建好的实例数据库对象:
    """通过类名称创建实例"""

    # 第一步：根据类名称查询本体类
    # get_class_by_name：传入类名，去数据库找到对应的本体类记录
    # 如果这个类不存在，这个函数内部直接抛404错误，代码直接终止
    ontology_class = get_class_by_name(session, class_name)

    # 第二步：调用真正创建实例的底层函数 create_instance
    return create_instance(
        session,   # 把数据库会话传下去
        # create_instance 需要接收 InstanceCreate 模型
        InstanceCreate(
            class_id=ontology_class.id, # 重点！查到的类里面取出id，底层方法只认id不认名字
            title=title,
            status=status,
            properties=properties or {}, # 如果传入的properties是None，替换成空字典{}，避免下游报错
        ),
    )


def relate(
    session: Session,
    source_id: str,
    target_id: str,
    relation_type: str,
    properties: dict | None = None,
) -> OntologyRelationORM:
    return create_relation(
        session,
        RelationCreate(
            source_id=source_id,
            target_id=target_id,
            type=relation_type,
            properties=properties or {},
        ),
    )



# 定义获取图谱数据的函数
def get_graph(session: Session, root_id: str | None = None, depth: int = 3) -> GraphRead:
    """Read the knowledge graph from Neo4j, falling back to the SQL store on error."""
    try:
        from app.infrastructure import graph_db

        graph_db.verify_connectivity()
        raw = graph_db.fetch_graph(root_id=root_id, depth=depth)
        nodes = [_build_node_summary(item) for item in raw["nodes"]]
        edges = [_build_edge_summary(item) for item in raw["edges"]]
        return GraphRead(nodes=nodes, edges=edges)
    except Exception:
        # Fallback to SQL store when Neo4j is unavailable so existing tests still pass.
        return _get_graph_from_sql(session, root_id=root_id, depth=depth)


def _build_node_summary(item: dict[str, Any]) -> OntologyInstanceRead:
    created_at = item.get("created_at") or datetime.utcnow()
    updated_at = item.get("updated_at") or created_at
    return OntologyInstanceRead(
        id=item["id"],
        class_id="",
        class_name=item.get("class_name", ""),
        title=item.get("title", ""),
        status=item.get("status", "draft"),
        properties=item.get("properties", {}) or {},
        created_at=created_at,
        updated_at=updated_at,
    )


def _build_edge_summary(item: dict[str, Any]) -> OntologyRelationRead:
    properties = item.get("properties", {}) or {}
    inferred = bool(item.get("inferred")) or bool(properties.get("inferred"))
    reason = properties.get("reason") or item.get("reason")
    return OntologyRelationRead(
        id=item.get("id") or f"{item['source_id']}-{item['type']}-{item['target_id']}",
        source_id=item["source_id"],
        target_id=item["target_id"],
        type=item["type"],
        properties=properties,
        inferred=inferred,
        reason=reason,
        created_at=datetime.utcnow(),
    )


def _get_graph_from_sql(session: Session, root_id: str | None = None, depth: int = 3) -> GraphRead:
    """Original SQL BFS implementation retained as the fallback path."""
    if not root_id:
        instances = session.scalars(
            select(OntologyInstanceORM)
            .options(joinedload(OntologyInstanceORM.ontology_class))
            .order_by(OntologyInstanceORM.created_at.asc())
            .limit(80)
        ).all()
        instance_ids = {instance.id for instance in instances}
    else:
        get_instance_or_404(session, root_id)
        instance_ids = {root_id}
        seen = {root_id}
        queue: deque[tuple[str, int]] = deque([(root_id, 0)])
        while queue:
            current_id, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            edges = session.scalars(
                select(OntologyRelationORM).where(
                    or_(
                        OntologyRelationORM.source_id == current_id,
                        OntologyRelationORM.target_id == current_id,
                    )
                )
            ).all()
            for edge in edges:
                for next_id in (edge.source_id, edge.target_id):
                    if next_id not in seen:
                        seen.add(next_id)
                        queue.append((next_id, current_depth + 1))
        instance_ids = seen

    nodes = session.scalars(
        select(OntologyInstanceORM)
        .options(joinedload(OntologyInstanceORM.ontology_class))
        .where(OntologyInstanceORM.id.in_(instance_ids))
    ).all()
    edges = session.scalars(
        select(OntologyRelationORM).where(
            OntologyRelationORM.source_id.in_(instance_ids),
            OntologyRelationORM.target_id.in_(instance_ids),
        )
    ).all()
    return GraphRead(
        nodes=[read_instance(node) for node in nodes],
        edges=[read_relation(edge) for edge in edges],
    )


def log_execution(
    session: Session,
    action: str,
    target_instance_id: str | None,
    status: str,
    duration_ms: int,
    message: str,
) -> OntologyInstanceORM:
    """
    创建一条执行日志实例
    封装方法:直接使用类名「ExecutionLog」生成日志记录
    :param session: SQLAlchemy数据库会话
    :param action: 执行操作名称，作为日志实例标题
    :param target_instance_id: 操作目标实例ID,可以为空
    :param status: 执行状态（成功/失败等）
    :param duration_ms: 执行耗时，单位毫秒
    :param message: 日志描述信息
    :return: 新建的日志实例ORM对象
    """
    # 调用封装函数，通过类名称创建实例
    return create_instance_by_class_name(
        session,                          # 向下传递数据库会话
        "ExecutionLog",                   # 指定本体类名称：日志类
        title=action,                     # 将操作名称作为实例标题
        status=status,                    # 传入执行状态
        properties={                      # 自定义属性字典，存放日志详情
            "target_instance_id": target_instance_id, # 被操作的实例ID
            "duration_ms": duration_ms,               # 执行耗时
            "message": message,                       # 日志详情文本
        },
    )
