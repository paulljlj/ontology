# 老代码归档（仅供学习对比）

> 本文件保存重构前 `backend/app/domain/constants.py` 和 `backend/app/domain/ontology.py`
> 里那些"独立维护的真相源"代码。**项目运行时不再使用它们**，只是历史快照，方便对比
> "老写法"和"OWL 新写法"。

---

## A. `constants.py` —— 老 `ClassName` / `RelationType` StrEnum

### 原始位置

[backend/app/domain/constants.py](../../backend/app/domain/constants.py)（全文）

### 老代码

```python
from enum import StrEnum


class ClassName(StrEnum):
    PROJECT = "Project"
    FEATURE = "Feature"
    SPEC = "Spec"
    USER_STORY = "UserStory"
    ACCEPTANCE = "Acceptance"
    CLARIFICATION = "Clarification"
    PLAN = "Plan"
    DATA_MODEL = "DataModel"
    CONTRACT = "Contract"
    ADR = "ADR"
    TASK = "Task"
    BUG = "Bug"
    CHECKLIST = "Checklist"
    REFLECTION = "Reflection"
    EXECUTION_LOG = "ExecutionLog"
    SERVICE_LOG = "ServiceLog"
    JENKINS_JOB = "JenkinsJob"
    FEISHU_MESSAGE = "FeishuMessage"


class RelationType(StrEnum):
    CONTAINS = "CONTAINS"
    DERIVES_TO = "DERIVES_TO"
    HAS_STORY = "HAS_STORY"
    HAS_ACCEPTANCE = "HAS_ACCEPTANCE"
    HAS_PLAN = "HAS_PLAN"
    HAS_TASK = "HAS_TASK"
    HAS_CHECKLIST = "HAS_CHECKLIST"
    HAS_REFLECTION = "HAS_REFLECTION"
    IMPLEMENTS = "IMPLEMENTS"
    BLOCKED_BY = "BLOCKED_BY"
    TRIGGERS = "TRIGGERS"
    PRODUCES_LOG = "PRODUCES_LOG"
```

### 为什么是老代码

类名 `Feature`、`Spec`、`Plan` 已经在 `ontology.py` 里用 `class Feature(Requirement): pass` 真实声明了；
关系名 `HAS_TASK`、`BLOCKED_BY` 也已经在 `ontology.py` 里用 `class HAS_TASK(ObjectProperty): pass` 真实声明了。

`constants.py` 把这些名字**又抄了一遍**——这是 OWL 迁移之前的中间状态。新代码让
`constants.py` 自动从 `ontology.py` 派生，访问方式（`ClassName.FEATURE` /
`RelationType.HAS_TASK`）不变，但真相源只剩一个：本体。

---

## B. `_CONCRETE_CLASSES` 元组

### 原始位置

[backend/app/domain/ontology.py:119-138](../../backend/app/domain/ontology.py#L119-L138)

### 老代码

```python
_CONCRETE_CLASSES = (
    Project,
    Feature,
    Spec,
    UserStory,
    Acceptance,
    Clarification,
    Plan,
    DataModel,
    Contract,
    ADR,
    Task,
    Bug,
    Checklist,
    Reflection,
    ExecutionLog,
    ServiceLog,
    JenkinsJob,
    FeishuMessage,
)
```

### 为什么是老代码

这是一个 Python 元组，里面手动列出所有"可实例化"的具体类。然后代码用这个元组：

1. 给每个类打 `instantiable = [True]` 标注（[ontology.py:161-163](../../backend/app/domain/ontology.py#L161-L163)）
2. 给每个类设置 `comment`（[ontology.py:163](../../backend/app/domain/ontology.py#L163)）
3. 生成 `AllDisjoint(list(_CONCRETE_CLASSES))` 公理（[ontology.py:166](../../backend/app/domain/ontology.py#L166)）

新写法直接给每个具体类声明时打上 `instantiable = [True]` 和 `comment`，`AllDisjoint` 用
`onto.classes()` 派生——不再单独维护这个列表。

---

## C. `_CLASS_DESCRIPTIONS` 字典

### 原始位置

[backend/app/domain/ontology.py:140-159](../../backend/app/domain/ontology.py#L140-L159)

### 老代码

```python
_CLASS_DESCRIPTIONS = {
    Project: "软件项目，是所有工程制品的根容器。",
    Feature: "业务能力或技术改进。",
    Spec: "需求规格说明。",
    UserStory: "面向角色和价值的用户故事。",
    Acceptance: "验收标准。",
    Clarification: "需求澄清问题。",
    Plan: "连接设计和任务的实现计划。",
    DataModel: "数据模型说明。",
    Contract: "API、事件或工具契约。",
    ADR: "架构决策记录。",
    Task: "可执行开发任务。",
    Bug: "缺陷或回归。",
    Checklist: "质量门禁检查清单。",
    Reflection: "Agent 或人的复盘记录。",
    ExecutionLog: "步骤执行日志。",
    ServiceLog: "服务运行日志。",
    JenkinsJob: "CI/CD 构建任务。",
    FeishuMessage: "飞书消息或回调。",
}
```

### 为什么是老代码

每个类的描述单独维护在这个字典里，然后通过循环
`_class.comment = [_CLASS_DESCRIPTIONS[_class]]` 把描述搬到 OWL 的 `comment` annotation 上。

新写法**直接在类定义旁边写** `comment`：

```python
class Feature(Requirement):
    pass
Feature.comment = ["业务能力或技术改进。"]
```

字典本身消失，描述仍然在 OWL 里，访问方式不变（`ontology.get_schema("Feature")["description"]`）。

---

## D. `_FIELD_TYPES` 字典

### 原始位置

[backend/app/domain/ontology.py:196-242](../../backend/app/domain/ontology.py#L196-L242)

### 老代码（节选）

```python
_FIELD_TYPES = {
    "title": (str, "string"),
    "status": (str, "string"),
    "description": (str, "string"),
    "source": (str, "string"),
    "tags": (str, "list"),
    "background": (str, "string"),
    "goal": (str, "string"),
    "version": (str, "string"),
    "clarifications": (str, "list"),
    "body": (str, "string"),
    "rule": (str, "string"),
    "question": (str, "string"),
    "answer": (str, "string"),
    "summary": (str, "string"),
    "architecture": (str, "string"),
    "method": (str, "string"),
    "path": (str, "string"),
    "decision": (str, "string"),
    "context": (str, "string"),
    "definition_of_done": (str, "list"),
    "estimate": (str, "string"),
    "passed": (str, "list"),
    "failed": (str, "list"),
    "checks": (str, "list"),
    "failed_checks": (str, "list"),
    "storage": (str, "string"),
    "environment": (str, "string"),
    "result": (str, "string"),
    "started_at": (str, "string"),
    "finished_at": (str, "string"),
    "action": (str, "string"),
    "duration_ms": (int, "integer"),
    "service": (str, "string"),
    "level": (str, "string"),
    "message": (str, "string"),
    "chat_id": (str, "string"),
    "content": (str, "string"),
    "sent_at": (str, "string"),
    "severity": (str, "string"),
    "repro_steps": (str, "list"),
    "ai_provider": (str, "string"),
    "target_instance_id": (str, "string"),
    "build_number": (int, "integer"),
    "triggered_at": (str, "string"),
    "mock": (bool, "boolean"),
}
```

### 状态：**保留**

这不是"老代码残留"，而是结构化数据。Owlready2 没有更优雅的批量声明 DatatypeProperty
的方式（每个属性本质都是一个独立的类声明），用字典循环生成比手写 40 行 `class title(DatatypeProperty, FunctionalProperty)` 声明更可维护。

但仍可读：每个 entry 的 key 是字段名，value 是 (Python 类型, payload_kind) 二元组，
循环里通过 `types.new_class(name, (DatatypeProperty, FunctionalProperty))` 真正建类。

---

## E. `_RELATION_DEFINITIONS` 字典

### 原始位置

[backend/app/domain/ontology.py:393-406](../../backend/app/domain/ontology.py#L393-L406)

### 老代码

```python
_RELATION_DEFINITIONS = {
    CONTAINS: (Thing, Thing, "包含关系"),
    DERIVES_TO: (Feature, Spec, "Feature 派生 Spec"),
    HAS_STORY: (Spec, UserStory, "Spec 包含 UserStory"),
    HAS_ACCEPTANCE: (Spec, Acceptance, "Spec 包含 Acceptance"),
    HAS_PLAN: (Spec, Plan, "Spec 包含 Plan"),
    HAS_TASK: (Plan, Task, "Plan 包含 Task"),
    HAS_CHECKLIST: (EngineeringArtifact, Checklist, "工程制品拥有 Checklist"),
    HAS_REFLECTION: (EngineeringArtifact, Reflection, "工程制品拥有复盘"),
    IMPLEMENTS: (Task, Contract, "Task 实现 Contract"),
    BLOCKED_BY: (Task, Task, "Task 被另一个 Task 阻塞"),
    TRIGGERS: (Feature, JenkinsJob, "Feature 触发 JenkinsJob"),
    PRODUCES_LOG: (Thing, Log, "节点产生日志"),
}


for _relation, (_domain, _range, _description) in _RELATION_DEFINITIONS.items():
    _relation.domain = [_domain]
    _relation.range = [_range]
    _relation.comment = [_description]
```

### 为什么是老代码

每条关系的 domain / range / comment 三元组在一个字典里集中声明，然后循环里赋值到
ObjectProperty 上。这是"批量赋值"风格的中间产物。

新写法**每条关系直接在自己的声明旁边写**：

```python
class HAS_TASK(ObjectProperty):
    pass
HAS_TASK.domain = [Plan]
HAS_TASK.range = [Task]
HAS_TASK.comment = ["Plan 包含 Task"]
```

更直观，关系名就在它的约束旁边，加新关系不需要改"字典+循环"两处。

---

## 新旧对照总结

| 老代码 | 新写法 |
|---|---|
| A. `constants.py` ClassName/RelationType enum | 自动从 ontology 派生，访问方式不变 |
| B. `_CONCRETE_CLASSES` 元组 | 直接给每个具体类打 `instantiable = [True]`，AllDisjoint 用 `onto.classes()` 派生 |
| C. `_CLASS_DESCRIPTIONS` 字典 | 在类声明旁边直接写 `Class.comment = ["..."]` |
| D. `_FIELD_TYPES` 字典 | **保留**（结构化数据，不是残留） |
| E. `_RELATION_DEFINITIONS` 字典 | 在 ObjectProperty 声明旁边直接写 `domain/range/comment` |

新写法的核心：**本体是唯一真相源**，Python 里不再有任何"独立维护的副本"。