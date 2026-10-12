# 系统架构

本项目采用“领域清晰优先”的四层结构，目的是让初学者能顺着目录理解系统。

## 1. Domain：本体语言

`backend/app/domain` 定义平台的核心词汇：

- `OntologyClass`：软件工程概念的类型，例如 Feature、Spec、Plan、Task。
- `OntologyInstance`：某个具体制品，例如“将存储从 PostgreSQL 扩展到 Neo4j”。
- `OntologyRelation`：实例之间的语义关系，例如 `DERIVES_TO`、`HAS_TASK`、`TRIGGERS`。

这层不关心数据库、HTTP、Jenkins 或 UI。

## 2. Application：工作流

`backend/app/application` 负责把本体实例组织成软件工程流程：

- 从 Feature 生成 Spec。
- 从 Spec 生成 Plan。
- 从 Plan 生成 Task。
- 对一个实例运行 Checklist。
- 写入 ExecutionLog 和 Reflection。

MVP 里的 AI 是规则模拟器，但接口已经按 `generate_spec`、`generate_plan`、`generate_tasks` 预留，未来可以替换为真实 LLM。

## 3. Infrastructure：外部世界

`backend/app/infrastructure` 放数据库和外部系统适配器：

- `database.py`：SQLAlchemy 连接。
- `orm.py`：PostgreSQL 表结构。
- `seed.py`：启动时写入本体类和示例数据。
- `mock_integrations.py`：模拟 Jenkins 和日志检索。
- `ai_provider.py`：规则型 AI Provider。

真实项目中，Jenkins、Elasticsearch、飞书、Neo4j 都应该在这一层接入。

## 4. API/UI：使用入口

`backend/app/api` 提供 HTTP API。React 前端通过这些 API 展示工作台。

重要设计原则是让 API 保持 Agent 友好：

- search：查找实例。
- get detail：读取实例详情。
- save instance：创建或更新实例。
- get graph：读取关系图。

这和未来 MCP 工具的形态是一致的。
