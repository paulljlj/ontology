# 演示流程

启动后端时，系统会自动写入一个示例项目：

```text
Ontology AI Coding Demo
```

并创建一个 Feature：

```text
将存储从 PostgreSQL 扩展到 Neo4j
```

## Web UI 演示

1. 打开 `http://localhost:5173`。
2. 左侧选择 `Feature`。
3. 点击示例 Feature。
4. 点击右侧 `跑完整工作流`。
5. 观察拓扑图、实例列表和详情面板变化。

系统会自动完成：

- Feature -> Spec
- Spec -> UserStory / Acceptance / Clarification
- Spec -> Plan
- Plan -> DataModel / Contract / ADR / Task
- Feature -> Checklist / Reflection / ExecutionLog
- Feature -> Mock JenkinsJob
- JenkinsJob -> Mock ServiceLog

## API 演示

先查询 Feature：

```bash
curl "http://localhost:8000/api/instances?class=Feature"
```

拿到 `id` 后生成 Spec：

```bash
curl -X POST "http://localhost:8000/api/workflows/spec-from-feature" ^
  -H "Content-Type: application/json" ^
  -d "{\"feature_id\":\"你的 Feature ID\"}"
```

继续生成 Plan：

```bash
curl -X POST "http://localhost:8000/api/workflows/plan-from-spec" ^
  -H "Content-Type: application/json" ^
  -d "{\"spec_id\":\"你的 Spec ID\"}"
```

查看拓扑图：

```bash
curl "http://localhost:8000/api/graph?root_id=你的 Feature ID"
```

## 你应该观察什么

重点不是文本生成得多漂亮，而是每个产物都变成了可查询、可关联、可复盘的本体实例。

这就是本项目和普通 AI 编程助手最大的区别。
