# API 说明

后端启动后可以打开：

```text
http://localhost:8000/docs
```

那里有 FastAPI 自动生成的交互式文档。

## 本体基础 API

### 查询 Class

```http
GET /api/classes
```

返回所有本体类型。

### 查询 Instance

```http
GET /api/instances?class=Feature&q=Neo4j&status=idea
```

参数都是可选的：

- `class`：本体类名。
- `q`：标题关键词。
- `status`：状态。

### 创建 Instance

```http
POST /api/instances
```

请求体：

```json
{
  "class_id": "Feature class id",
  "title": "新的 Feature",
  "status": "idea",
  "properties": {
    "priority": "high"
  }
}
```

### 更新 Instance

```http
PATCH /api/instances/{id}
```

### 创建 Relation

```http
POST /api/relations
```

请求体：

```json
{
  "source_id": "上游实例 ID",
  "target_id": "下游实例 ID",
  "type": "DERIVES_TO",
  "properties": {}
}
```

### 查询 Graph

```http
GET /api/graph?root_id=实例 ID
```

如果不传 `root_id`，返回最近的一批节点和关系。

## 工作流 API

### Feature 生成 Spec

```http
POST /api/workflows/spec-from-feature
```

```json
{
  "feature_id": "Feature ID"
}
```

### Spec 生成 Plan

```http
POST /api/workflows/plan-from-spec
```

```json
{
  "spec_id": "Spec ID"
}
```

### Plan 生成 Task

```http
POST /api/workflows/tasks-from-plan
```

```json
{
  "plan_id": "Plan ID"
}
```

### 运行 Checklist

```http
POST /api/workflows/run-checklist
```

```json
{
  "root_id": "实例 ID"
}
```

## Mock DevOps API

### 触发 Jenkins

```http
POST /api/integrations/jenkins/trigger
```

```json
{
  "feature_id": "Feature ID",
  "environment": "staging"
}
```

### 搜索日志

```http
POST /api/integrations/logs/search
```

```json
{
  "service": "ontology-core-service",
  "level": "info",
  "q": "started"
}
```
