# 本体智能体工作台（Ontology Agent Workbench）

一个本体驱动的智能体执行平台。它把需求、设计、任务、日志、CI/CD 等软件工程对象统一抽象成本体实例，并用关系图描述它们之间的语义连接。

第一版不直接调用真实大模型、Jenkins、Elasticsearch 或飞书，而是使用规则模拟和 Mock Adapter，让你先看懂完整闭环。

## 你能体验什么

- 创建 Feature，并一键生成 Spec、Plan、Task。
- 查看 Project、Feature、Spec、Task 等本体实例。
- 通过拓扑图理解“需求如何衍生为设计，设计如何拆解为任务”。
- 运行 Checklist，检查 Feature 是否缺少 Spec、Plan、Task。
- 触发 Mock Jenkins 构建，并查询 Mock Service Log。
- 阅读清晰的中文文档，理解每层代码在做什么。
- 在同一页面输入目标并一键执行，查看本体判断、推理规则、Task、Skill、MCP 与产物的实时过程。
- 下载清洗数据、Excel 分析报表、结果摘要和可追溯执行清单。

## 技术栈

- 后端：Python 3.12 + FastAPI + SQLAlchemy
- 前端：React + Vite + TypeScript
- 数据库：PostgreSQL 16
- 本地编排：Docker Compose

## 快速启动

首次在新电脑安装、使用 SQLite 启动、使用 Docker 启动以及页面操作方法，请阅读：[使用与启动说明](docs/使用与启动说明.md)。

### 1. 启动 PostgreSQL 和后端

```bash
docker compose up -d postgres backend
```

后端地址：

```text
http://localhost:8000
```

API 文档：

```text
http://localhost:8000/docs
```

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端地址：

```text
http://localhost:5173
```

进入页面后直接使用“本体智能体工作台”：

1. 用自然语言描述数据整理目标和期望指标。
2. 点击“运行需求”，DataSourceResolver 会通过 MCP 选择数据源；未配置外部连接器时会明确使用内置演示数据。
3. 左侧流程图逐步展示 Task、Skill、MCP 绑定、状态与输出。
4. 右侧知识图谱同步展示 Goal、Spec、Task、Skill、Artifact 和推理关系。
5. 执行完成后点击流程末端的“查看结果”，下载清洗 CSV、Excel 报表、结果摘要和执行清单。

同一能力也通过 MCP 暴露为 `inspect_tabular_file`、`execute_data_report` 和
`get_execution_run`，供外部 Agent 编排调用。

### 3. 不使用 Docker 启动后端

如果你已经有 PostgreSQL，可以在 `backend` 目录执行：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set DATABASE_URL=postgresql+psycopg://ontology:ontology@localhost:5432/ontology_ai
uvicorn app.main:app --reload
```

如果你只是想先预览功能，也可以临时使用 SQLite：

```bash
cd backend
pip install -r requirements.txt
set DATABASE_URL=sqlite+pysqlite:///./ontology_demo.db
uvicorn app.main:app --reload
```

SQLite 预览模式适合学习和演示；正式运行仍推荐使用 PostgreSQL。

## 推荐学习路径

1. 先读 `docs/ontology-model.md`，理解 Class、Instance、Relation。
2. 再读 `docs/workflow-demo.md`，照着演示走一遍。
3. 然后读 `docs/architecture.md`，理解代码分层。
4. 最后打开 `http://localhost:8000/docs` 对照 API。

## 项目结构

```text
backend/
  app/
    domain/          本体核心模型和规则
    application/     工作流用例
    infrastructure/  数据库、Mock 集成、AI Provider
    api/             HTTP API
frontend/
  src/               React 工作台
docs/                中文说明文档
```

## 默认账号和权限

MVP 默认本地单用户使用，没有登录系统。后续可以在本体层加入 User、Role、Permission 等 Class。
