# Ontology AI Coding MVP —— 系统汇报文档

> 适用版本：当前 `main` 工作区（OWL 统一裁定 + Neo4j 图谱 + MCP 工具化）
> 面向读者：项目导师、合作伙伴、新加入的研发同学
> 阅读时长：≈ 25 分钟

---

## 0. 30 秒摘要

我们做了一个 **"用本体描述软件工程，再用 AI 在本体上工作"** 的教学型 MVP：
- **本体（OWL）** 是规则的唯一来源；所有写入都先过 OWL 校验。
- **知识图谱（Neo4j）** 镜像 SQL 中的工程制品，并增量叠加 Pellet 推导的"虚线边"。
- **LLM** 通过 **MCP 工具** 调用同一套校验入口，保证它也无法绕过 OWL。
- **前端** 是一个语义拓扑工作台（React + Cytoscape），点节点、看关系、跑工作流。

整套系统对外只暴露 `http://localhost:8000/api` 一组 REST + 一组 MCP 工具；OWL 文件可一键导出，可加载到 Protégé 复核。

---

## 1. 系统能力地图

| 一级能力 | 二级能力 | 入口 |
| --- | --- | --- |
| 本体治理 | OWL 单一源 → `engineering.owl` | `app/domain/ontology.py` + `scripts/export_ontology.py` |
| | Pellet 一致性推理 | `app/domain/reasoner.py::validate_with_pellet` |
| | 传递闭包物化（虚线边） | `app/domain/reasoner.py::compute_inferred_edges` + `scripts/materialize_inferred.py` |
| 写入一致性 | REST/MCP/Workflow/Seed 全部走 `create_instance` / `relate` | `app/application/ontology_service.py` |
| | 校验失败统一 422 + 错误明细 | `reasoner.ValidationResult` |
| 知识图谱 | SQL → Neo4j ETL | `scripts/etl_to_neo4j.py` |
| | `GET /api/graph` 优先 Neo4j，断线降级 SQL | `ontology_service.get_graph` |
| 智能体 | 规则版 AI（零依赖） | `app/infrastructure/ai_provider.py::RuleBasedAIProvider` |
| | 真 LLM（OpenAI 兼容） | `LLMProvider`（同文件） |
| 工作流 | Feature → Spec → Plan → Tasks → Checklist → Mock Jenkins | `app/application/workflows.py` + `app/api/routes.py` |
| MCP | FastMCP stdio 暴露 7 个工具 + 1 个 Resource | `app/mcp/server.py` |
| | MCP 客户端 Agent，含失败回退 | `app/application/agent.py` |
| 前端 | 拓扑图（点选、过滤、缩放、虚线边） | `frontend/src/components/Topology.tsx` |
| | Composer（新建 Feature）+ 详情面板 + 工作流按钮 | `frontend/src/App.tsx` |

---

## 2. 分层架构总览

```
┌────────────────────────────────────────────────────────────────────┐
│  Frontend  (React + Vite + TS + Cytoscape)                          │
│   ── App.tsx / Topology.tsx / api.ts / types.ts                     │
└──────────────────────────────┬─────────────────────────────────────┘
                               │  fetch JSON
┌──────────────────────────────▼─────────────────────────────────────┐
│  REST  (FastAPI, prefix=/api)                                       │
│   ── routes.py  →  ontology_service  →  reasoner (OWL 校验)         │
└──────┬───────────────────────────────────────┬─────────────────────┘
       │ SQLAlchemy                            │ Neo4j Driver
┌──────▼──────────┐                  ┌─────────▼─────────────┐
│  PostgreSQL/SQL │                  │  Neo4j 5.26 Community  │
│  三张表：       │                  │  - OntologyInstance   │
│  - ontology_   │                  │  - OntologyClass      │
│    classes     │                  │  - asserted 边        │
│  - ontology_   │                  │  - inferred 边 (虚线) │
│    instances   │                  └───────────────────────┘
│  - ontology_   │
│    relations   │
└──────┬──────────┘
       │
┌──────▼──────────────────────────────────────────────────────────┐
│  Domain Layer  (Python + Owlready2)                                │
│   ── ontology.py: 类/属性/限制/枚举, AllDisjoint, Functional, Transitive │
│   ── reasoner.py: 闭世界校验 + Pellet 一致性 + 传递闭包推导           │
│   ── schemas.py: Pydantic 读写模型                                  │
└──────┬───────────────────────────────────────────────────────────┘
       │ (可导出 engineering.owl)
┌──────▼────────────┐        ┌────────────────────────────────────┐
│  MCP Server (stdio)│        │  MCP Client (Agent)                │
│   7 tools + 1 res  │◄──────│  StdioServerParameters + ClientSession│
│   (FastMCP)        │ JSON-RPC                                  │
└────────────────────┘        └────────────────────────────────────┘
```

代码遵循 DDD 分层：
- `domain/` — 业务规则本体，不依赖框架
- `application/` — 用例编排（写入、工作流、ETL 触发）
- `infrastructure/` — 数据库、Neo4j、LLM Provider、Mock Adapter
- `api/`、`mcp/` — 对外接口
- `frontend/` — 浏览器侧

---

## 3. OWL 本体实现（单一规则源）

### 3.1 设计目标

> "任何写入都必须先过 OWL 校验；Python 不再按 `if class_name == 'Feature'` 这种硬编码裁定字段合法性。"

代码入口：[backend/app/domain/ontology.py](../backend/app/domain/ontology.py)

### 3.2 类层级（手工建模）

```
owl:Thing
├── engineering:EngineeringArtifact
│   ├── engineering:Requirement
│   │   ├── engineering:Feature           (叶子实例化)
│   │   └── engineering:UserStory        (叶子实例化)
│   ├── engineering:Specification
│   │   ├── engineering:Spec             (叶子)
│   │   ├── engineering:Acceptance       (叶子)
│   │   └── engineering:Clarification    (叶子)
│   ├── engineering:Design
│   │   ├── engineering:Plan             (叶子，HAS_TASK min 1)
│   │   ├── engineering:DataModel        (叶子)
│   │   ├── engineering:Contract         (叶子)
│   │   └── engineering:ADR              (叶子)
│   └── engineering:Execution
│       ├── engineering:Task             (叶子)
│       ├── engineering:Bug              (叶子)
│       ├── engineering:Checklist        (叶子)
│       ├── engineering:Reflection       (叶子)
│       └── engineering:JenkinsJob       (叶子)
├── engineering:Log
│   ├── engineering:ExecutionLog
│   └── engineering:ServiceLog
└── engineering:ControlledValue
    ├── engineering:PriorityValue        (low/medium/high/critical)
    └── engineering:LayerValue           (domain/application/api/infrastructure/test)
```

工程上做了三层防呆：
1. **AllDisjoint** 三大顶层分支 → 不允许一个实例同时是 EngineeringArtifact 与 Log；
2. **AllDisjoint** 所有"叶子可实例化"类 → 避免歧义归类（Feature 不可能是 Plan）；
3. **AllDisjoint** 枚举个体 → priority="high" 不会同时被当作 layer。

### 3.3 数据属性（字段建模）

把"必填 / 选填 / 类型"统一用 OWL 公理表达，例如 Feature：

```python
_constrain_fields(
    Feature,
    required={"title": str},
    optional={"status": str, "description": str, "priority": PriorityValue,
              "source": str, "tags": str, "background": str},
)
```

展开后等价于给 `Feature` 加上一组 restriction：

```turtle
Feature ⊑ ∃ title . string            # 必填
Feature ⊑ ≤ 1 title . string          # 函数性（最多 1 个 title）
Feature ⊑ ∀ priority . PriorityValue  # 取值范围
Feature ⊑ ≤ 1 priority . PriorityValue
```

枚举本体化是亮点：

```python
with onto:
    high = PriorityValue("high")
AllDifferent([low, medium, high, critical])
```

这样 `priority` 的合法值就是 OWL 中实实在在的 named individuals，而不是 Python `["low","medium","high","critical"]` 这种容易被改坏的列表。

### 3.4 对象属性（关系建模）

```python
class CONTAINS(ObjectProperty):           pass
class DERIVES_TO(ObjectProperty, FunctionalProperty):  pass  # 最多一个 Spec
class HAS_PLAN(ObjectProperty):           pass
class HAS_TASK(ObjectProperty):           pass  # Plan ⊑ ∃ HAS_TASK . Task
class BLOCKED_BY(ObjectProperty, TransitiveProperty):   pass  # 传递闭包
class TRIGGERS(ObjectProperty):           pass
class PRODUCES_LOG(ObjectProperty):       pass
# ...
```

关键点：
- `DERIVES_TO` 标 `FunctionalProperty` → 一个 Feature 最多派生出 1 个 Spec，违反时 REST/MCP 都会拒绝；
- `BLOCKED_BY` 标 `TransitiveProperty` → T1→T2、T2→T3 蕴含 T1→T3；
- `Plan HAS_TASK min 1 Task` → Plan 必须至少有一个 Task（创建 Plan 时尚未满足，OWL 用"延迟"校验；本 MVP 在 `validate_with_pellet` 与完整性 checklist 阶段统一检测）。

### 3.5 OWL 导出与重载

```bash
python -m scripts.export_ontology        # 写 engineering.owl
python -m scripts.check_consistency      # 用 Pellet 加载 engineering.owl 跑一致性
```

`engineering.owl` 是 RDF/XML，可用 Protégé 打开、修改、回灌；Python 端通过 `Owlready2.World` 在隔离 World 里加载，跑推理不会污染进程级本体。

### 3.6 闭世界 vs. 开放世界（关键决策）

OWL 是开放世界假设：声明 `Feature ⊑ ∃ title . string` **不意味着**"现在请求里没传 title 就报错"——它只约束存在性。要做"创建时缺 title 就 422"，得在闭世界适配层查当前 payload。

我们在 `reasoner.py::validate_instance` 里这样处理：

```python
schema = ontology.get_schema(class_name)         # 从 OWL restrictions 动态生成
fields = schema["fields"]
values = {"title": title, "status": status, **properties}

# 1) 未声明字段 → 422
unknown = sorted(set(values) - set(fields))

# 2) 必填字段缺失 → 422
for field_name in schema["required_fields"]:
    if field_name not in values or _is_empty(values[field_name]):
        errors.append(...)

# 3) 类型/枚举值检查 → 422
for field_name, value in values.items():
    error = _validate_value(field_name, value, fields[field_name])
```

判定规则来自 OWL（restriction、range、enum individuals），不是 Python 字典。哪天把 `priority` 的可选值改成 `["low","medium","high","urgent"]`，只需要改 ontology.py 里 4 个 `PriorityValue(...)` 实例——所有调用方自动跟随。

---

## 4. Neo4j 图谱实现

### 4.1 角色

| 存储 | 角色 | 写入时机 |
| --- | --- | --- |
| PostgreSQL/SQLite | 业务真实状态（断言事实） | REST / MCP / Workflow / Seed 唯一权威写入 |
| Neo4j | 关系查询副本 + 推导事实 | ETL 镜像 + materialize 增量叠加 |

### 4.2 节点 / 边约束

```cypher
CREATE CONSTRAINT ontology_instance_id
  IF NOT EXISTS FOR (n:OntologyInstance) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT ontology_class_name
  IF NOT EXISTS FOR (n:OntologyClass)   REQUIRE n.name IS UNIQUE;

CREATE INDEX ontology_instance_class   IF NOT EXISTS FOR (n:OntologyInstance) ON (n.class_name);
CREATE INDEX ontology_instance_title   IF NOT EXISTS FOR (n:OntologyInstance) ON (n.title);
CREATE INDEX ontology_instance_status  IF NOT EXISTS FOR (n:OntologyInstance) ON (n.status);
```

每个 `OntologyInstance` 节点除业务字段外，把 `properties` 整体序列化到 `properties_json`，避免建动态列。

### 4.3 ETL：`scripts/etl_to_neo4j.py`

```python
for row in _iter_instances(session):
    graph_db.upsert_instance(row.id, row.ontology_class.name, ...)
for row in _iter_relations(session):
    graph_db.relate_instances(row.id, row.source_id, row.target_id, row.type, ...)
```

幂等：所有写操作都是 `MERGE`。可以反复跑；同样命令也可作为冷启动恢复工具。

验证：开发库 685 instances / 635 relations，ETL 后 Neo4j 完全一致。

### 4.4 写入时的双向同步

为避免"Neo4j 长期漂移"，`create_instance` / `relate` 在 SQL 提交成功后，**同步** 调用 `graph_db.upsert_instance` / `relate_instances`。所以：

- REST → 后端写入 SQL → 同步 Neo4j
- MCP `create_instance` 工具 → 后端写入 SQL → 同步 Neo4j
- Agent 跑完整工作流 → 同上

Neo4j 同步失败**不回滚** SQL（保证写入幂等），失败只记日志；下次 ETL 会自愈。

### 4.5 读取：`GET /api/graph?root_id=...`

```python
def get_graph(session, root_id=None, depth=3):
    try:
        graph_db.verify_connectivity()
        raw = graph_db.fetch_graph(root_id=root_id, depth=depth)
        return GraphRead(nodes=..., edges=...)
    except Exception:
        return _get_graph_from_sql(session, root_id, depth)   # 优雅降级
```

Cypher 子图查询（节选）：

```cypher
MATCH (root:OntologyInstance {id: $root_id})
MATCH path = (root)-[*1..3]-(neighbor:OntologyInstance)
WITH collect(DISTINCT neighbor) AS nodes
UNWIND nodes AS n
OPTIONAL MATCH (n)-[r]->(m:OntologyInstance) WHERE m IN nodes
WITH nodes, collect(DISTINCT r) AS edges
RETURN nodes, edges
```

返回结构会带 `inferred: true` 字段；Cytoscape 据此把虚线边画成 **橙色虚线**。

---

## 5. Pellet 推理与"虚线边"物化

### 5.1 两层校验

| 层级 | 触发点 | 实现 | 速度 |
| --- | --- | --- | --- |
| 闭世界快速校验 | 每次写入 | `reasoner.validate_instance` / `validate_relation` | 毫秒 |
| 开放世界一致性 | 测试 / 显式调用 | `reasoner.validate_with_pellet` | 秒级 |

Pellet 跑在隔离 `World`，不污染进程本体；只在检查/测试阶段使用，不会拖慢每个 REST 请求。

### 5.2 物化传递闭包

代码入口：`app/domain/reasoner.py::compute_inferred_edges`

```python
# 1) 把 SQL 里所有 instance 复制成 owlready2 individuals
# 2) 把所有 asserted 边转成 owlready2 object property assertions
# 3) sync_reasoner_pellet(infer_property_values=True)
# 4) 遍历 TransitiveProperty，取"非断言"的 (s, t) 对
```

示例链：
```
Task A --BLOCKED_BY--> Task B --BLOCKED_BY--> Task C
                                   ↓ Pellet 推导
Task A --BLOCKED_BY--> Task C   （写入 Neo4j，inferred=true）
```

### 5.3 物化脚本 / 端点

```bash
python -m scripts.materialize_inferred       # CLI
POST /api/reasoning/materialize               # REST 触发
```

物化流程：
1. `graph_db.clear_inferred_edges()` —— 清掉旧的 `r.inferred = true` 边
2. `reasoner.compute_inferred_edges(...)` —— 算新的
3. 对每条 `(src, tgt, type, reason)` 调 `graph_db.upsert_inferred_edge(...)` —— 写 Neo4j

边 id 是确定性的 `infer:<type>:<src>:<tgt>`，可重复运行幂等。

---

## 6. MCP（Model Context Protocol）实现

### 6.1 为什么引入 MCP

让 LLM 能直接调用我们的"安全操作"：每次 MCP 工具调用都走后端的 OWL 校验入口，等价于一个被 OWL 守住的工具箱。LLM **不可能**绕过 OWL。

### 6.2 MCP Server：[app/mcp/server.py](../backend/app/mcp/server.py)

通过 FastMCP 注册的 7 个工具 + 1 个 Resource：

| 工具名 | 入参 | 后端动作 |
| --- | --- | --- |
| `search_ontology(query, class_name?, status?)` | 关键词 | `ontology_service.list_instances` |
| `describe_class(class_name)` | 类名 | 从 OWL 读 schema + 关联 ObjectProperty |
| `create_instance(class_name, title, status, properties)` | 实例字段 | **OWL 校验** + SQL + Neo4j 同步 |
| `relate(source_id, target_id, relation_type, properties)` | 关系 | **OWL domain/range 校验** + SQL + Neo4j |
| `query_graph(root_id?, depth, limit)` | 根节点 | Neo4j 子图查询（带 inferred 标记） |
| `search_logs(service?, level?, q?)` | 关键字 | mock 日志集成 |
| `trigger_jenkins(feature_id, environment)` | feature | mock Jenkins 集成 |
| Resource `ontology://classes` | — | 返回所有可实例化类的描述 |

启动方式：
```bash
python -m app.mcp.server                  # stdio transport
```

### 6.3 MCP Client（Agent）：[app/application/agent.py](../backend/app/application/agent.py)

LLM 走完一个完整 Feature 工作流的样例：

```python
async def run_agent(feature_title):
    server = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp.server"])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

            feature = await _invoke(session, "create_instance",
                {"class_name": "Feature", "title": feature_title, ...})
            spec = await _invoke(session, "create_instance",
                {"class_name": "Spec", "title": f"{feature_title} Spec", ...})
            await _invoke(session, "relate",
                {"source_id": feature.id, "target_id": spec.id, "relation_type": "DERIVES_TO"})

            plan = await _invoke(session, "create_instance", {"class_name": "Plan", ...})
            await _invoke(session, "relate",
                {"source_id": spec.id, "target_id": plan.id, "relation_type": "HAS_PLAN"})

            for title in task_titles:
                task = await _invoke(session, "create_instance", {"class_name": "Task", ...})
                await _invoke(session, "relate",
                    {"source_id": plan.id, "target_id": task.id, "relation_type": "HAS_TASK"})

            graph = await _invoke(session, "query_graph", {"root_id": feature.id, "depth": 3})
```

任何一次工具失败 → 抛 `RuntimeError` → 进入 `run_with_fallback` 降级路径：用规则版 workflow 不依赖 MCP 也能跑通（方便排错和 CI）。

### 6.4 MCP 与 Neo4j / OWL 的关系

```
LLM  ──MCP tool call──▶  MCP Server  ──▶  reasoner (OWL 校验)
                                              │
                              ┌───────────────┼───────────────┐
                              ▼                               ▼
                       SQL (SQLAlchemy)              Neo4j (同步)
```

LLM 永远只能做"调用 OWL 校验过的工具"这件事。

---

## 7. 端到端示例：用户登录 Feature

> 用户在前端输入"用户登录"，点击"跑完整工作流"，到拓扑图出现完整链条。
> 下图展示了**所有**经过的代码路径和存储操作。

### 7.1 用户操作

1. 打开浏览器 → `http://localhost:5173`
2. 在 Composer 输入框填标题 `用户登录`，回车
3. 选优先级（高）、填描述、点"创建 Feature"
4. 左侧导航选 "Feature" → 列表里出现新条目 → 选中它
5. 右侧详情面板点"跑完整工作流（LLM）"

### 7.2 完整调用链（逐步）

| # | 触发 | 调用 | 后端动作 | 存储写入 |
| --- | --- | --- | --- | --- |
| 1 | 浏览器 | `POST /api/instances` | `routes.post_instance` → `ontology_service.create_instance` → `reasoner.validate_instance("Feature", ...)` | — |
| 2 | 同上 | 校验通过 | `session.add(OntologyInstanceORM(...))` + `graph_db.upsert_instance(...)` | SQL:1 row, Neo4j:1 node |
| 3 | 浏览器 | `GET /api/classes` + `GET /api/instances?class=Feature` + `GET /api/graph?root_id=...` | `routes.get_classes` / `list_instances` / `get_graph` | 只读 |
| 4 | 浏览器 | `POST /api/workflows/spec-from-feature` | `workflows.generate_spec_from_feature` → `ai_provider.generate_spec(feature)` (LLM or rule-based) | — |
| 5 | 同上 | `create_instance(Spec)` + `relate(feature, spec, DERIVES_TO)` | OWL 校验 + SQL + Neo4j | SQL:1 实例 1 边, Neo4j:1 node 1 edge |
| 6 | 浏览器 | `POST /api/workflows/plan-from-spec` | 同上：Spec → Plan (HAS_PLAN) | SQL:1 实例 1 边 |
| 7 | 浏览器 | `POST /api/workflows/tasks-from-plan` | 循环：每个 Task → `relate(plan, task, HAS_TASK)` | SQL:N 实例 N 边 |
| 8 | 浏览器 | `POST /api/workflows/run-checklist` | 创建 Checklist 节点 + Reflection 节点 | SQL:2 实例 |
| 9 | 浏览器 | `POST /api/integrations/jenkins/trigger` | mock 触发 JenkinsJob → 写 ServiceLog | SQL:2 实例 1 边 |
| 10 | 浏览器 | `POST /api/integrations/logs/search` | mock 查日志 | 只读 |
| 11 | 浏览器 | `POST /api/reasoning/materialize` (可选) | Pellet 推导 → 写 Neo4j 虚线边 | Neo4j:虚线边 |
| 12 | 浏览器 | `GET /api/graph?root_id=...` | 从 Neo4j 读子图 | 只读 |
| 13 | Cytoscape | 渲染节点 + 边（虚线边用 `inferred=true` 标记） | — | — |

### 7.3 数据流时序图

```
Browser ──▶ FastAPI ──▶ reasoner ──▶ SQL (主)
                │            │
                │            └──────▶ Neo4j (同步, 断言边)
                │
                └──────▶ (workflow 完成)
                         │
                         ▼ (可选)
                  /api/reasoning/materialize
                         │
                         ▼
                   reasoner.compute_inferred_edges
                         │
                         ▼
                   Pellet (隔离 World)
                         │
                         ▼
                   Neo4j 虚线边 (inferred=true)
                         │
                         ▼
Browser ◀── /api/graph ◀── Neo4j
```

### 7.4 一次失败演示（OWL 拦截）

假如前端不小心把 `priority` 写成 `"urgent"`：

```http
POST /api/instances
{ "class_id": "<Feature id>", "title": "用户登录", "status": "idea",
  "properties": { "priority": "urgent" } }

→ 422 Unprocessable Entity
{
  "detail": [{
    "msg": "[「Feature.priority」值「urgent」不合法，必须是 ['critical','high','low','medium'] 之一]"
  }]
}
```

这个错误**不是**来自前端校验，也不是来自 Python if 字典，而是来自 OWL 读出的枚举实例集合。

---

## 8. 前端 ↔ 后端交互详解

### 8.1 前端代码地图

```
frontend/
├── index.html
├── package.json         (依赖：cytoscape, react-cytoscapejs, lucide-react, ...)
├── src/
│   ├── main.tsx         入口
│   ├── App.tsx          主页面：sidebar / composer / 拓扑 / 列表 / 详情
│   ├── api.ts           fetch 封装 (10 个 REST 调用)
│   ├── types.ts         OntologyClass / Instance / Relation / Graph
│   ├── styles.css       样式
│   └── components/
│       └── Topology.tsx Cytoscape 封装（cose 布局、过滤、缩放、虚线边）
```

### 8.2 `api.ts` 暴露的全部接口

```ts
api.classes()                                      // GET /classes
api.instances(className?, q?)                      // GET /instances
api.graph(rootId?)                                 // GET /graph
api.createInstance({ class_id, title, status?, properties? })
                                                   // POST /instances
api.specFromFeature(featureId)                     // POST /workflows/spec-from-feature
api.planFromSpec(specId)                           // POST /workflows/plan-from-spec
api.tasksFromPlan(planId)                          // POST /workflows/tasks-from-plan
api.runChecklist(rootId)                           // POST /workflows/run-checklist
api.triggerJenkins(featureId, env?)                // POST /integrations/jenkins/trigger
api.searchLogs()                                   // POST /integrations/logs/search
```

### 8.3 关键 UI 状态机

```
[初始]
  │
  ├── 选中 sidebar 一类 → setSelectedClass → 重新拉 instances + graph
  │
  ├── 输入新 Feature 标题 → composer.title
  │     │
  │     ├── "创建 Feature" → POST /instances → setSelected → 刷新 graph
  │     │
  │     └── "跑完整工作流" → 6 个连续 POST → 刷新 graph
  │
  ├── 拓扑图点节点 → onSelect(instance) → setSelected → 重新拉 graph
  │
  └── 拓扑图过滤下拉 → setFilter → 前端本地 hide 节点 / 边
```

### 8.4 拓扑组件与"虚线边"

Cytoscape 数据构造（节选）：

```tsx
const edges = graph.edges.map(edge => ({
  data: {
    id: edge.id ?? `${edge.source_id}-${edge.type}-${edge.target_id}`,
    source: edge.source_id, target: edge.target_id,
    label: edge.type,
    inferred: Boolean(edge.inferred ?? edge.properties?.inferred),
  }
}));

// 样式选择器
{ selector: 'edge[inferred = "true"]',
  style: { 'line-style': 'dashed',
           'line-color': '#fa541c',
           'target-arrow-color': '#fa541c',
           'text-background-color': '#fff7e6' } }
```

效果：所有 `inferred=true` 的边在拓扑图里呈**橙色虚线**，并在 label 文本后面挂 `(transitive_closure)` 之类提示。

---

## 9. 上手使用指南

### 9.1 启动栈（Docker Compose）

```bash
cd ontology
docker compose up -d postgres backend neo4j

# 后端 8000，前端另开终端：
cd frontend && npm install && npm run dev
# → http://localhost:5173
```

### 9.2 不使用 Docker

```bash
# 1) Postgres（任选）或者直接用 SQLite：DATABASE_URL=sqlite+pysqlite:///./ontology_demo.db
# 2) Neo4j 5.x 自启，端口 7687，账号 neo4j / ontology
# 3) 后端
cd backend
pip install -r requirements.txt
python -m scripts.export_ontology
uvicorn app.main:app --reload --port 8000

# 4) ETL + 物化（冷启动必须）
python -m scripts.etl_to_neo4j
python -m scripts.materialize_inferred
```

### 9.3 体验最短路径

1. 打开 `http://localhost:5173`
2. 左侧点 **Feature** → 看种子数据
3. 在拓扑图里点任意节点 → 右侧出现详情
4. 在 Composer 输入 `Demo`，点"跑完整工作流"
5. 拓扑图出现 1 Feature → 1 Spec → 1 Plan → N Tasks 的橙色链条
6. （可选）点击 `POST /api/reasoning/materialize` → 拓扑图出现 **虚线** 边

### 9.4 调用 MCP 工具（直接）

```bash
# Terminal A: 启动 MCP server
cd backend
python -m app.mcp.server

# Terminal B: 跑 agent（自动用 stdio 连 A）
python -m app.application.agent "我的登录功能"
```

输出 JSON 包含完整 transcript：

```json
{
  "feature": {...}, "spec": {...}, "plan": {...}, "tasks": [...],
  "graph": { "nodes": 28, "edges": 27 },
  "transcript": [
    { "tool": "create_instance", "arguments": {"class_name":"Feature","title":"我的登录功能"}, "result": {...} },
    ...
    { "tool": "query_graph", "result": {"nodes":28,"edges":27} }
  ]
}
```

---

## 10. 关键设计决策与权衡

| 决策 | 选项 | 我们的选择 | 理由 |
| --- | --- | --- | --- |
| 校验放哪一层 | Python 字典 vs OWL | OWL + 闭世界适配 | 单一源；规则可被 Protégé 编辑；可被 Pellet 复用 |
| Pellet 调用频率 | 每次写入 vs 测试时 | 测试 + 显式 materialize | 启动 JVM 太重，闭世界快速校验已经能挡住 90% 错误 |
| Neo4j 写入时机 | 异步队列 vs 同步双写 | 同步双写（失败不回滚） | MVP 阶段简单优先；失败下次 ETL 自愈 |
| 物化边存储 | SQL vs 仅 Neo4j | 仅 Neo4j（`inferred=true`） | 推断事实不是业务断言，不应污染 SQL 真值表 |
| MCP 失败 | 报错 vs 回退 | `run_with_fallback` 双路径 | CI / 演示不能因为 MCP 抖动挂掉 |
| 前端图库 | D3 vs Cytoscape vs vis.js | Cytoscape | 内置 cose 布局 + 选择器语法，适合 OWL 风格节点-边 |
| OWL 重载祖先链 | trust `prop.ancestors()` | 用 in-process ontology 检测 TransitiveProperty | Owlready2 重载后 `TransitiveProperty` 不在 ancestors 里 |

---

## 11. 测试与验证

```bash
cd backend
pytest tests/ -q
```

| 测试 | 验证内容 |
| --- | --- |
| `test_ontology_rules.py` | OWL 字段/枚举/关系 domain-range 校验正确 |
| `test_api_workflow.py::test_create_*` | REST 创建实例 / 关系正确 |
| `test_api_workflow.py::test_feature_*` | Feature → Spec → Plan → Tasks 端到端 |
| `test_api_workflow.py::test_*validation*` | 非法 priority / 缺 title / 错 domain-range → 422 |

手动验证：
1. **OWL 拦截** —— 浏览器提交 priority="urgent"，确认 422。
2. **Pellet 一致性** —— `python -m scripts.check_consistency` 全绿。
3. **Neo4j 同步** —— `python -m scripts.etl_to_neo4j` 跑两次，节点/边数量不变。
4. **传递闭包** —— 手动建 `Task A -BLOCKED_BY-> Task B -BLOCKED_BY-> Task C`，`materialize` 后拓扑图出现 A→C 虚线。

---

## 12. 下一步路线图

| 主题 | 后续工作 |
| --- | --- |
| OWL 表达力 | 加入属性链（property chain）实现"Feature 间接关联 Plan" 等更复杂的派生关系 |
| Pellet 使用面 | 把 validate_with_pellet 接入 CI 在每次合并时跑 |
| MCP 协议 | 加入 `MCP sampling` 让 server 反向调用 LLM 完成更多推理 |
| 图谱查询 | Cypher 模板暴露：影响域 / 反向追溯 / 关键路径 |
| 前端体验 | 时间轴视图、批量编辑、多人协作（OT/CRDT） |

---

## 13. 关键文件速查

| 关心什么 | 看哪里 |
| --- | --- |
| 本体建模 | `backend/app/domain/ontology.py` |
| 校验与 Pellet | `backend/app/domain/reasoner.py` |
| 写入入口（统一过 OWL） | `backend/app/application/ontology_service.py::create_instance` / `relate` |
| 工作流编排 | `backend/app/application/workflows.py` |
| Neo4j 驱动 | `backend/app/infrastructure/graph_db.py` |
| ETL | `backend/scripts/etl_to_neo4j.py` |
| 传递闭包物化 | `backend/scripts/materialize_inferred.py` |
| MCP Server | `backend/app/mcp/server.py` |
| MCP Client | `backend/app/application/agent.py` |
| REST 路由 | `backend/app/api/routes.py` |
| 前端入口 | `frontend/src/App.tsx` |
| 拓扑图组件 | `frontend/src/components/Topology.tsx` |
| 启动脚本 | `start.ps1`、`docker-compose.yml` |

---

## 14. 一句话总结

> 用一份 OWL 本体同时约束 SQL / Neo4j / LLM / 人类四类"消费者"，让规则不再散落在 Python 字典、Prompt 文本、SQL 触发器里——**任何修改只改一处**。
