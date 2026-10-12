# 本体模型说明

本体模型可以理解为“给软件工程世界建一套统一语言”。

## Class

Class 是概念类型。MVP 默认包含：

- Project            项目/产品，代表一个独立的软件工程或业务系统
- Feature            业务能力或技术改进，是较大颗粒度的功能需求
- Spec               规格说明，对 Feature 或功能的详细行为描述
- UserStory          用户故事，从最终用户视角描述"谁、想要什么、为什么"
- Acceptance         验收标准，验证 UserStory 或 Task 是否完成的条件
- Clarification      澄清记录，对需求或设计中不明确之处的补充说明
- Plan               计划，包含排期、里程碑、版本发布规划
- DataModel          数据模型，定义实体结构、字段类型及表间关系
- Contract           接口契约，定义 API 的请求/响应格式及协议规范
- ADR                架构决策记录，记录重要技术选型和设计决策及其原因
- Task               任务，可分配执行的最小工作单元
- Bug                缺陷，系统中的错误、异常或不符合预期的行为
- Checklist          检查清单，上线或验收前的自检项列表
- Reflection         复盘记录，对迭代、需求或事件的总结与改进反思
- ExecutionLog       执行日志，人为操作或流程执行的记录
- ServiceLog         服务日志，系统运行时产生的应用日志
- JenkinsJob         Jenkins 任务，CI/CD 流水线的构建或部署作业
- FeishuMessage      飞书消息，通过飞书发送的通知、告警或交互消息

例如 `Feature` 是一个 Class，表示“业务能力或技术改进”。

## Instance

Instance 是某个 Class 的具体对象。

例子：

```json
{
  "class_name": "Feature",
  "title": "将存储从 PostgreSQL 扩展到 Neo4j",
  "status": "idea",
  "properties": {
    "priority": "high"
  }
}
```

它不是一段提示词，而是一个结构化的软件工程对象。

## Relation

Relation 是两个 Instance 之间的语义边。

常见关系：

- `CONTAINS`：包含。
- `DERIVES_TO`：从一个制品推导出另一个制品。
- `HAS_STORY`：Spec 拥有 User Story。
- `HAS_ACCEPTANCE`：Spec 拥有验收标准。
- `HAS_PLAN`：Spec 拥有实现计划。
- `HAS_TASK`：Plan 拆解出任务。
- `HAS_CHECKLIST`：实例拥有检查清单。
- `TRIGGERS`：实例触发外部动作。
- `PRODUCES_LOG`：构建或服务产生日志。

## 为什么这对 AI 友好

传统 AI 编程助手常常依赖长提示词描述上下文。这个项目把上下文变成结构化拓扑：

- AI 先搜索实例。
- 再读取详情。
- 再沿关系找到上游需求、下游任务、相关日志。
- 最后保存新的实例或关系。

这样可以减少上下文爆炸，也更容易复盘 AI 到底做了什么。
