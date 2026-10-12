# Ontology AI Coding MVP 项目总结与技术文档

## 1. 项目定位

这个项目是一个“本体驱动 AI 软件工程平台”的教学型 MVP。它的核心思想不是简单地把需求、任务、计划、日志等对象放进数据库，而是把它们统一定义为“本体中的实例”，并通过 OWL 规则、语义关系和知识图谱保证这些对象之间的合法性与可追溯性。

项目的价值在于：

- 用统一的语义模型描述软件工程对象。
- 用 OWL 约束控制字段合法性和关系合法性。
- 在 SQL + Neo4j 中双轨保存实例和关系。
- 让 AI 工作流、MCP 工具、REST API 都走同一套规则。
- 为前端提供可视化拓扑图和工作流编排能力。

核心入口：

- [backend/app/main.py](../backend/app/main.py)
- [backend/app/domain/ontology.py](../backend/app/domain/ontology.py)
- [backend/app/application/workflows.py](../backend/app/application/workflows.py)
- [backend/app/api/routes.py](../backend/app/api/routes.py)
- [frontend/src/App.tsx](../frontend/src/App.tsx)

---

## 2. 项目目标和业务场景

项目的目标非常明确：构建一个“从需求到设计、再到任务和验证”的本体化软件工程闭环。

它支持的一个典型场景是：

1. 用户在前端创建一个 Feature。
2. 后端验证其字段和关系是否合法。
3. 根据 Feature 生成对应的 Spec。
4. 由 Spec 生成 Plan。
5. 由 Plan 拆分成多个 Task。
6. 运行 Checklist 检查完整性。
7. 触发 Mock Jenkins 构建。
8. 查询 Mock Service Log。
9. 在图谱中查看 Feature → Spec → Plan → Task 之间的语义关系。

这正是“工程制品被视为知识图谱节点，而流程则是关系和规则引导的工作流”的典型实现。

---

## 3. 项目结构说明

项目整体划分为以下若干部分：

### 3.1 后端核心

- [backend/app/domain](../backend/app/domain)
  - 存放本体定义、OWL 规则、校验逻辑和 Pydantic DTO。
- [backend/app/application](../backend/app/application)
  - 存放工作流和业务编排逻辑。
- [backend/app/infrastructure](../backend/app/infrastructure)
  - 存放数据库、Neo4j、AI Provider、Mock Adapter、Feishu 集成。
- [backend/app/api](../backend/app/api)
  - 对外 REST API。
- [backend/app/mcp](../backend/app/mcp)
  - MCP 工具层，用于外部 AI 客户端调用。

### 3.2 前端

- [frontend/src/App.tsx](../frontend/src/App.tsx)
- [frontend/src/components/Topology.tsx](../frontend/src/components/Topology.tsx)
- [frontend/src/api.ts](../frontend/src/api.ts)

前端是一个语义拓扑工作台，主要负责：

- 列出本体类。
- 创建 Feature。
- 查看实例和关系。
- 运行工作流。
- 使用图谱视图观察工程对象和边。

### 3.3 文档

- [docs/system-report.md](system-report.md)
- [docs/architecture.md](architecture.md)
- [docs/ontology-model.md](ontology-model.md)
- [docs/workflow-demo.md](workflow-demo.md)

这些文档构成了项目的知识沉淀，尤其是系统汇报文档已经覆盖了整体设计。

---

## 4. 设计原则：本体优先而不是硬编码优先

这是项目最重要的设计点。

项目不再让代码里大量写：

- if class_name == "Feature"
- if relation == "HAS_TASK"
- if field_name == "priority"

而是把合法类、字段、关系、枚举值都放在 OWL 本体中描述。这样做的好处是：

- 规则集中管理。
- 前后端和 MCP 都能从同一套本体读取约束。
- 规则变更不再依赖代码分散修正。
- AI 工作流和 REST 接口自然遵守同一套语义约束。

这个原则在 [backend/app/domain/ontology.py](../backend/app/domain/ontology.py) 中体现得最强。

---

## 5. 本体层：OWL 才是真相源

### 5.1 核心文件

- [backend/app/domain/ontology.py](../backend/app/domain/ontology.py)
- [backend/app/domain/reasoner.py](../backend/app/domain/reasoner.py)

### 5.2 本体结构

本体定义了工程对象的核心层次：

- Project
- Feature
- Spec
- Plan
- Task
- Checklist
- Reflection
- JenkinsJob
- FeishuMessage
- Log
- ControlledValue

此外还有对象属性和数据属性：

- CONTAINS
- DERIVES_TO
- HAS_PLAN
- HAS_TASK
- BLOCKED_BY
- TRIGGERS
- PRODUCES_LOG

这些关系不仅是“图上的边”，而且有 OWL 语义约束，例如：

- DERIVES_TO 是 FunctionalProperty，表示一个 Feature 最多派生一个 Spec。
- BLOCKED_BY 是 TransitiveProperty，表示传递闭包。
- Plan 至少要有一个 HAS_TASK。

### 5.3 字段约束

在 ontology.py 中，字段被注册为 DatatypeProperty，并在每个类上通过 `_constrain_fields` 挂载限制。

例如 Feature 定义了：

- required: title
- optional: status, description, priority, source, tags, background

这样一来，字段是否必填、是否可选、是否为枚举、是否为整数、是否为布尔值，最终都能从 OWL 规则反推出。

### 5.4 枚举本体化

优点在于“枚举不只是字符串列表，而是 OWL 个体”。比如：

- low
- medium
- high
- critical

它们作为 PriorityValue 实例存在，且用 AllDifferent 约束互斥，这样更符合语义学模型。

---

## 6. 校验层：闭世界适配与 OWL 校验

核心文件：

- [backend/app/domain/reasoner.py](../backend/app/domain/reasoner.py)

这里的设计很关键：

- OWL 是开放世界假设；
- 但业务上需要“创建实例时如果字段缺失就直接拒绝”。

因此 reasoner.py 里做了一个桥接：

- 从本体读 schema。
- 识别 required_fields 和 optional_fields。
- 检查未知字段。
- 检查必填/空值。
- 检查类型和枚举值。

例如 validate_instance 会检查：

- 字段是否存在于本体声明中。
- 必填字段是否缺失。
- 字段值是否符合类型要求。
- 枚举值是否合法。

这使得写入入口不需要在每个地方重复写验证代码，而是统一使用 reasoner.validate_instance。

---

## 7. 数据存储层：双存储架构

这个项目使用了一个非常有代表性的双存储思路：

### 7.1 SQL / PostgreSQL

核心文件：

- [backend/app/infrastructure/orm.py](../backend/app/infrastructure/orm.py)
- [backend/app/infrastructure/database.py](../backend/app/infrastructure/database.py)

主要表：

- ontology_classes
- ontology_instances
- ontology_relations
- approval_mappings

ORM 层中，用 UUID 作为主键，适合分布式/跨平台场景，也方便前后端传输对象 ID。

### 7.2 Neo4j

核心文件：

- [backend/app/infrastructure/graph_db.py](../backend/app/infrastructure/graph_db.py)

Neo4j 被用于知识图谱场景：

- 存储实例节点。
- 存储关系边。
- 允许按根节点扩展查看局部子图。
- 通过 inferred edge 表示推导出的虚线边。

优点：

- 关系查询自然。
- 可视化拓扑更直观。
- 更适合语义网络和图查询。

缺点：

- 需要维护一致性。
- 本体和图数据库需要同步更新。

项目在 get_graph 中实现了优先读取 Neo4j，失败则回退 SQL。这个设计非常实用。

---

## 8. 服务层：Application 编排逻辑

核心文件：

- [backend/app/application/ontology_service.py](../backend/app/application/ontology_service.py)
- [backend/app/application/workflows.py](../backend/app/application/workflows.py)

### 8.1 ontology_service

这个文件是整个业务中最重要的编排层之一，负责：

- 读取实例。
- 创建实例。
- 更新实例。
- 创建关系。
- 列出实例。
- 获取图谱。

它遵循以下设计：

- 先查类和实例是否存在。
- 再执行 OWL 校验。
- 然后写入数据库。
- 通过 read_instance / read_relation 转换为对外 DTO。

这保证了“所有入口都遵循一致的写入规则”。

### 8.2 workflows

工作流层负责把业务流程编排出来。关键方法包括：

- generate_spec_from_feature
- generate_plan_from_spec
- generate_tasks_from_plan
- run_checklist

其架构特点是：

- 先拿到一个 Feature。
- 通过 AI Provider 生成对应的 Spec/Plan/Tasks。
- 自动创建本体实例。
- 建立语义关系。
- 记录执行日志。

这也是整个系统“把工程对象视为可追踪制品”的体现。

---

## 9. API 层：FastAPI 暴露统一接口

核心文件：

- [backend/app/api/routes.py](../backend/app/api/routes.py)

API 提供以下能力：

- /api/health
- /api/classes
- /api/instances
- /api/instances/{id}
- /api/relations
- /api/graph
- /api/workflows/spec-from-feature
- /api/workflows/plan-from-spec
- /api/workflows/tasks-from-plan
- /api/workflows/run-checklist
- /api/integrations/jenkins/trigger
- /api/integrations/logs/search
- /api/reasoning/materialize

其中最重要的是：

- 任何写入都先经过本体校验。
- API 层很薄，是协调层，不承担真正的业务规则。
- 图谱查询会优先读取 Neo4j。
- 某些写入如 Feishu 审批会触发门禁逻辑。

---

## 10. AI Provider 层：规则型 AI 和 LLM 接口兼容

核心文件：

- [backend/app/infrastructure/ai_provider.py](../backend/app/infrastructure/ai_provider.py)
- [backend/app/infrastructure/llm_provider.py](../backend/app/infrastructure/llm_provider.py)

设计非常清晰：

- 默认采用 RuleBasedAIProvider。
- 如果配置了 OpenAI 风格 API key，则自动切到 LLMProvider。

它实现了统一协议：

- generate_spec
- generate_plan
- generate_tasks

因此，无论是规则型模拟器还是真实大模型，工作流调用方式完全一致。

这个设计放大了“AI 只是一个能力提供者，而业务流程仍然由本体约束”的思路。

---

## 11. MCP 与 Agent：让 AI 也必须遵守本体规则

核心文件：

- [backend/app/mcp/server.py](../backend/app/mcp/server.py)
- [backend/app/application/agent.py](../backend/app/application/agent.py)

MCP 是这个项目的一个亮点。

它暴露了诸如以下工具：

- search_ontology
- describe_class
- create_instance
- relate
- query_graph
- search_logs
- trigger_jenkins
- send_feishu_message

这些工具并不是随意暴露的“万能接口”，而是通过本体规则托管的能力层。这样一来，MCP 客户端即使是一个 LLM Agent，也不能绕过 OWL 校验。

这意味着本项目尝试实现的是：

- AI 生成内容，不是无约束自由发挥。
- 真实的业务动作必须经过本体层审核。

这是很多“AI 应用”容易忽略的关键点。

---

## 12. Feishu 集成与审批门禁

这一部分是项目中最有工程现实感的扩展：

- [backend/app/infrastructure/feishu_client.py](../backend/app/infrastructure/feishu_client.py)
- [backend/app/infrastructure/feishu_events.py](../backend/app/infrastructure/feishu_events.py)

### 12.1 审批门禁

在工作流中，如果开启 require_feishu_approval，Spec 会先进入 pending_review 状态，而不是直接 ready。

这能实现如下流程：

1. Feature 生成 Spec。
2. 创建飞书审批单。
3. 相关映射保存到 approval_mappings。
4. 只有审核通过，后续 Plan / Task 才可继续生成。

### 12.2 事件回调

Feishu 事件监听负责：

- 监听审批状态更新。
- 根据 instance_code 反查 Spec。
- 若审批通过或拒绝，更新本体实例状态。
- 同步到 Neo4j。

这个设计体现了“审批意见会反写回工程对象”的闭环思想。

---

## 13. 前端：拓扑工作台

核心文件：

- [frontend/src/App.tsx](../frontend/src/App.tsx)
- [frontend/src/components/Topology.tsx](../frontend/src/components/Topology.tsx)
- [frontend/src/api.ts](../frontend/src/api.ts)

前端做的不是普通 CRUD 页面，而是一个“知识图谱工作台”。

它的主要功能包括：

- 选择本体类，如 Feature、Spec、Plan、Task。
- 对实例进行列表展示。
- 用图谱视图绘制节点与边。
- 基于点选实例显示详情。
- 提供工作流执行入口：Spec/Plan/Tasks/Checklist/Jenkins。

Topology.tsx 使用 Cytoscape 渲染图，支持：

- 缩放。
- 过滤节点类别。
- 选中高亮。
- 根据边的 inferred 属性绘制虚线推导边。

这让用户能非常直观看到“需求如何展开为设计与任务”。

---

## 14. 运行流程和典型用户体验

以一个 Feature 为例：

1. 用户在前端创建 Feature。
2. 请求 POST /api/instances。
3. application.ontology_service.create_instance 先合并声明字段和额外字段。
4. reasoner.validate_instance 对 title、status、priority 等字段进行检查。
5. 若通过，实例入库。
6. 用户点击“跑完整工作流”。
7. 后端调用 generate_spec_from_feature。
8. Spec、UserStory、Acceptance、Clarification 自动写入。
9. 再调用 generate_plan_from_spec，生成 Plan、DataModel、Contract、ADR。
10. 再调用 generate_tasks_from_plan，生成 Task。
11. 调用 run_checklist 执行检查。
12. 调用 trigger_mock_jenkins 模拟构建。
13. 调用 search_mock_logs 检索日志。
14. 前端展示图谱和执行结果。

这条链路很典型：

- 数据是本体实例。
- 流程是工作流。
- 可视化是图谱。
- 验证是本体规则。

---

## 15. 设计亮点

### 15.1 统一规则源

规则来自 OWL，而不是散落在 Python 代码中。这个设计对后续扩展非常有价值。

### 15.2 多入口统一校验

REST API、MCP 工具、工作流和初始化脚本都走同一套校验入口。这样不会出现“某个入口绕过规则”的情况。

### 15.3 图谱 + SQL 双模式

SQL 用于稳定结构化存储，Neo4j 用于语义查询和可视化。两者互补，且实现了失败回退。

### 15.4 AI 不是自由发挥，而是受约束地工作

这个项目表达了一个非常成熟的工程思路：

- AI 负责生成内容；
- 本体负责限制合法性；
- 流程负责把内容变成工程制品。

### 15.5 教学友好

项目中大量中文注释、分层清晰、命名自然、文档完善，适合用于学习：

- 本体建模。
- 图谱驱动架构。
- OWL 约束设计。
- FastAPI + SQLAlchemy 的工程代码实践。

---

## 16. 技术风险和局限

这个项目是 MVP，因此也存在一定局限：

### 16.1 业务面还比较教学型

它更偏“可演示、可学习”，而不是“企业级生产系统”。

### 16.2 数据模型较轻

虽然有 OWL 本体，但实际业务对象还是相对固定，很多概念并没有继续扩展到真实用户、权限、团队、发布对象等完整领域模型。

### 16.3 真实集成还没有真正落地

当前项目默认走 Mock Adapter，真实的 LLM、Jenkins、飞书、Neo4j 仍需配置环境，并且强依赖 .env 和运行基础设施。

### 16.4 图结构一致性需要维护

SQL 和 Neo4j 双存储意味着需要更严谨的同步机制；如果某一层出错，可能出现图谱与数据库不一致的问题。

---

## 17. 建议的阅读顺序

如果要深入理解这个项目，推荐顺序如下：

1. [README.md](../README.md)
2. [docs/architecture.md](architecture.md)
3. [docs/ontology-model.md](ontology-model.md)
4. [backend/app/domain/ontology.py](../backend/app/domain/ontology.py)
5. [backend/app/domain/reasoner.py](../backend/app/domain/reasoner.py)
6. [backend/app/application/ontology_service.py](../backend/app/application/ontology_service.py)
7. [backend/app/application/workflows.py](../backend/app/application/workflows.py)
8. [backend/app/api/routes.py](../backend/app/api/routes.py)
9. [backend/app/mcp/server.py](../backend/app/mcp/server.py)
10. [frontend/src/App.tsx](../frontend/src/App.tsx)
11. [frontend/src/components/Topology.tsx](../frontend/src/components/Topology.tsx)

---

## 18. 一句话总结

这个项目的本质不是“一个简单的 CRUD 系统”，而是一个“用 OWL 定义软件工程语义、用图谱可视化工程对象、用 AI 工作流编排工程活动”的原型平台。它把软件工程抽象为知识图谱中的实例和关系，并用规则驱动 AI 围绕这些对象持续工作，这使它非常适合作为本体驱动软件工程的教学和原型基础。
