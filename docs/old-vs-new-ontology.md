# 类与关系：老写法 vs 新写法（OWL）对照

> 目的：用项目里真实存在的代码片段，展示同一个"知识"原本要散在 5、6 个文件里写，
> 现在只要在 `backend/app/domain/ontology.py` 一个地方声明即可。
> 推理机（Pellet）的好处先不讲，本文只讲"定义方式"本身的差异。
ontology.py ← 唯一真相源（手写、IDE 支持、可读性好）
    ↓ export_ontology()
engineering.owl ← 派生产物（机器可读、跨工具交换、推理机输入）
---
## 概览：知识从"散在多处"变成"集中一处"

原本那种写法（Python 字符串 + 字典 + 散落的 if 分支），每个类、每条关系都得在多个文件
里"各说一遍"，靠人脑把它们联系起来。新写法（OWL）则是把类、关系、字段、约束、枚举
**全部声明成形式化公理**，一份本体就是唯一真相源，下面所有用到的地方都从它派生。

---

## 对照一：`Feature` 这个类是怎么定义的

### 老写法 —— Feature 的定义散落在 5 个地方
实际上没有类的定义，纯粹是靠Feature这个字符串去到处文件找，找他的字段要求，字段也是字符串，找他的关系。也是写成了if Feature必须有title

**① 类名只是个字符串** —— [backend/app/domain/constants.py:7](../../backend/app/domain/constants.py#L7)
```python
class ClassName(StrEnum):
    PROJECT = "Project"
    FEATURE = "Feature"
    SPEC = "Spec"
    ...
```

**② 类描述单独存一个 Python 字典** —— [backend/app/domain/ontology.py:140-159](../../backend/app/domain/ontology.py#L140-L159)
```python
_CLASS_DESCRIPTIONS = {
    Project: "软件项目，是所有工程制品的根容器。",
    Feature: "业务能力或技术改进。",
    Spec: "需求规格说明。",
    ...
}
```
**③ 字段类型又在另一个字典里声明一次** —— [backend/app/domain/ontology.py:196-242](../../backend/app/domain/ontology.py#L196-L242)
```python
_FIELD_TYPES = {
    "title": (str, "string"),
    "priority": (str, "enum"),
    "background": (str, "string"),
    ...
}
```

**④ API 入参用 Pydantic 又声明一次字段** —— [backend/app/domain/schemas.py:21-26](../../backend/app/domain/schemas.py#L21-L26)
```python
class InstanceCreate(BaseModel):
    class_id: str
    title: str
    status: str = "draft"
    properties: dict[str, Any] = Field(default_factory=dict)
```

> **痛点**：这 5 处里没有任何一处写着"Feature 就是 Feature"。类名只是字符串、字段只是
> 字典里的 key。要改一个字段类型，得记得 5 处全改；少改一处就出现 bug。

---
### 新写法结构
EngineeringArtifact                ← 一切工程制品的根（[ontology.py:37](../../backend/app/domain/ontology.py#L37))）
├── Requirement                    ← "要做什么"
│   ├── Feature
│   └── UserStory
├── Specification                  ← "怎么描述需求"
│   ├── Spec
│   ├── Acceptance
│   └── Clarification
├── Design                         ← "怎么设计"
│   ├── Plan
│   ├── DataModel
│   ├── Contract
│   └── ADR
└── Execution                      ← "怎么动手做"
    ├── Task
    ├── Bug
    ├── Checklist
    ├── Reflection
    ├── ExecutionLog
    ├── ServiceLog
    ├── JenkinsJob
    └── FeishuMessage
一、
    ontology.py:165-167 
    AllDisjoint([EngineeringArtifact, Log, ControlledValue])
    AllDisjoint(list(_CONCRETE_CLASSES))
    AllDisjoint([PriorityValue, LayerValue])
    意思是 Feature 不可能是 Plan，Task 不可能是 Spec——这四类之间是互斥的。
    因为推理机，是按照逻辑的推理，可能feature spec同时满足条件。让一个实例 又是feature 又是spec 这里不行。让他们互斥
二、
    如果想让所有 Requirement（Feature + UserStory）都能被 PRIORITIZED_BY 关系引用，直接：
    PRIORITIZED_BY.domain = [Requirement]

### 新写法 —— 一个文件、一行代码搞定

[backend/app/domain/ontology.py:67-68](../../backend/app/domain/ontology.py#L67-L68)
```python
class Feature(Requirement):
    pass
```

仅此而已。所有"Feature 必须有 title"、"priority 必须是 high/medium/low 之一"、
"Feature 必须有 description"——这些字段约束都在下面用 restriction 集中声明。
---

### 为什么这么写？语法解读

```python
with onto:
class Feature(Requirement):
    pass
```
| `with onto:` | 进入 OWL 本体上下文。下面所有类/属性自动登记到当前 ontology。 |
| `class Feature(...)` | 在本体里声明一个 OWL Class。 |
| `(Requirement)` | `Feature` 是 `Requirement` 的子类，等价于 OWL 公理 `Feature ⊑ Requirement`。 |
| `pass` | Owlready2 要求类体不能为空，`pass` 占位。注意：这个类是真的"空"——它的字段约束在别处通过 `is_a.append(Restriction)` 加上去。 |

### 属性需要在哪里？is_a
    首先，OWL核心规则都是通过我们的subClassOf也就是继承父类来传递。
    is_a 是类的父类限制。意思比如把X放入is_a,那Feature实例必须满足父类，也是父类实例 或者说满足is_a里的限制。
    X = title.min(1, str) 时 → "任何 Feature 实例都必须满足『有 ≥1 个 title 是字符串』" 
### Restriction机制
    Restrction 就是**"把字段需要打包成一个匿名类"的机制。OWL 没有专门语法说"字段需要"，它只有 subClassOf。所以你必须把它包装成一个"类"（匿名类 / Restriction），然后才能放到 subClassOf 里去。所以字段约束 = Restriction + 放进 is_a。 
### 本项目怎么加入is_a 
    ontology.py:265-276：函数constrain_fields

    def _constrain_fields(
        owl_class: type,
        *,
        required: dict[str, Any],
        optional: dict[str, Any] | None = None,
    ) -> None:
        for name, value_type in required.items():
            field = onto[name]
            owl_class.is_a.extend([field.only(value_type), field.min(1, value_type), field.max(1, value_type)])
        for name, value_type in (optional or {}).items():
            field = onto[name]
            owl_class.is_a.extend([field.only(value_type), field.max(1, value_type)])


    调用fields
    _constrain_fields(
        Spec,
        required={"title": str, "goal": str},
        optional={"status": str, "version": str, "background": str, "clarifications": str, "ai_provider": str},
    )
    _constrain_fields(
        Feature,
        required={"title": str},
        optional={"status": str, "description": str, "priority": PriorityValue, "source": str, "tags": str, "background": str},
    )

    给 Feature 加必填字段 title，等价于：
    Feature.is_a.append(title.only(str))     # title 的值只能是字符串
    Feature.is_a.append(title.min(1, str))    # title 至少要 1 个
    Feature.is_a.append(title.max(1, str))    # title 至多 1 个
### 一个具体的is_a
Feature.is_a = [
    Requirement,                          # 父类：Feature ⊑ Requirement
    title.only(str),                      # 字段约束：所有 Feature 实例的 title 值必须是字符串
    title.min(1, str),                    # 字段约束：必须有 ≥1 个 title
    title.max(1, str),                    # 字段约束：至多 1 个 title
    status.max(1, str),                   # 字段约束：status 至多 1 个
    description.max(1, str),
    priority.max(1, PriorityValue),       # 字段约束：priority 至多 1 个、必须是 PriorityValue 实例
    source.max(1, str),
    tags.max(1, str),
    background.max(1, str),
]
---

## 对照二：类和类的关系怎么定义的 比如`HAS_TASK` 这条关系是怎么定义的

### 老写法 —— 关系的定义散落在 4 个地方

**① 关系名只是个字符串** —— [backend/app/domain/constants.py:31](../../backend/app/domain/constants.py#L31)
```python
class RelationType(StrEnum):
    CONTAINS = "CONTAINS"
    DERIVES_TO = "DERIVES_TO"
    HAS_TASK = "HAS_TASK"
    ...
```

**② 端点白名单（domain/range）单独一个字典**（原本会叫 `RELATION_SCHEMAS`）——
概念上等价于现在的 `_RELATION_DEFINITIONS`，见 [backend/app/domain/ontology.py:393-406](../../backend/app/domain/ontology.py#L393-L406)
```python
_RELATION_DEFINITIONS = {
    HAS_TASK: (Plan, Task, "Plan 包含 Task"),
    ...
}
```

**③ 关系校验函数里又写一遍 if 分支**（原本会有，现在已统一成 reasoner 里的通用校验）——
概念上等价于：
```python
def validate_relation(rel_type, source_cls, target_cls):
    if rel_type == "HAS_TASK" and source_cls != "Plan":
        raise Error("HAS_TASK 必须从 Plan 出发")
    if rel_type == "HAS_TASK" and target_cls != "Task":
        raise Error("HAS_TASK 必须指向 Task")
```

**④ 调用现场还要硬编码一次关系名** —— [backend/app/application/workflows.py:179](../../backend/app/application/workflows.py#L179)
```python
relate(session, plan.id, task.id, RelationType.HAS_TASK)
```

> **痛点**：HAS_TASK 的"从 Plan 到 Task"这件事在 4 个地方各说一遍。改一处漏改另一处，
> 校验函数会和新字典打架。

---

### 新写法 —— 4 行声明，全套自动
### ObjectProperty
    OWL 里有"两种东西"，别混为一谈
OWL 本体里只有两大类实体，平行存在：
OWL 本体
├── OWL Class（类）            ← 描述"实例是什么类别"
│   ├── EngineeringArtifact
│   ├── Requirement
│   ├── Feature
│   └── ...
└── OWL ObjectProperty（对象属性）← 描述"实例之间怎么连"
    ├── HAS_TASK
    ├── BLOCKED_BY
    ├── DERIVES_TO
    └── ...
HAS_TASK 不是类——它是 ObjectProperty 类型的一个具体实体，跟 Feature（Class 类型的具体实体）平级。
ObjectProperty专门描述实例和实例之间的关系。
ObjectProperty —— 关联两个实例（"Feature 派生出 Spec"）
DatatypeProperty —— 关联实例和数据值（"Feature 的 title 是字符串"）
AnnotationProperty —— 注释（"这个类的描述是 xxx"）

[backend/app/domain/ontology.py:371-373](../../backend/app/domain/ontology.py#L371-L373)
```python
class HAS_TASK(ObjectProperty):
    pass
class HAS_PLAN(ObjectProperty):
    pass

```

[backend/app/domain/ontology.py:399, 408-411](../../backend/app/domain/ontology.py#L408-L411)
```python
# 在 _RELATION_DEFINITIONS 字典里：
_RELATION_DEFINITIONS = {
    CONTAINS: (Thing, Thing, "包含关系"),
    DERIVES_TO: (Feature, Spec, "Feature 派生 Spec"),
    HAS_STORY: (Spec, UserStory, "Spec 包含 UserStory"),
    HAS_ACCEPTANCE: (Spec, Acceptance, "Spec 包含 Acceptance"),
    HAS_PLAN: (Spec, Plan, "Spec 包含 Plan"),
    HAS_TASK: (Plan, Task, "Plan 包含 Task"),
    HAS_CHECKLIST: (EngineeringArtifact, Checklist, "工程制品拥有 Checklist"),
    HAS_REFLECTION: (EngineeringArtifact, Reflection, "工程制品拥有 Reflection"),
    IMPLEMENTS: (Task, Contract, "Task 实现 Contract"),
    BLOCKED_BY: (Task, Task, "Task 被另一个 Task 阻塞"),
    TRIGGERS: (Feature, JenkinsJob, "Feature 触发 JenkinsJob"),
    PRODUCES_LOG: (Thing, Log, "节点产生日志"),
}
#给 ObjectProperty 设置 domain/range（端点允许规则）
for _relation, (_domain, _range, _description) in _RELATION_DEFINITIONS.items():
    _relation.domain = [_domain]
    _relation.range = [_range]
    _relation.comment = [_description]
#plan最少要有一条执行任务 
plan同时发送字段和类关系约束  上面循环是plan包含task 也就是可以有，这里添加条件必须有
也就是有了plan必须有对应task执行
Plan.is_a.append(HAS_TASK.min(1, Task))

---

### 为什么这么写？语法解读
# 第 1 步：定义 HAS_TASK 这个对象属性本体（[ontology.py:371-373](../../backend/app/domain/ontology.py#L371-L373)))
class HAS_TASK(ObjectProperty):
    pass

# 第 2 步：声明它的端点约束（[ontology.py:408-411](../../backend/app/domain/ontology.py#L408-L411)))
HAS_TASK.domain = [Plan]      # 起点必须是 Plan 实例
HAS_TASK.range = [Task]       # 终点必须是 Task 实例
---

---

## 总结对比表

| 维度 | 老写法 | 新写法（OWL） |
|---|---|---|
| 定义位置 | 散在 5、6 个文件 | 集中在 `ontology.py` 一个文件 |
| 定义形式 | Python 字符串、字典、if 分支 | OWL 公理（subClassOf / ObjectProperty / Restriction / NamedIndividual） |
| 一个"Feature 类"是什么 | 一个字符串 + 一堆配置项拼凑 | 一个 OWL Class，有继承关系、有自身公理 |
| 一条"HAS_TASK 关系"是什么 | 一个字符串 + 一份白名单 + 一段 if 校验 | 一个 ObjectProperty，有 domain/range 公理 |
| "Plan 必须包含 Task"是什么 | 手写 BFS + 列表比对 | 一行 OWL Restriction |
| 加一个新类 | 改 6 个文件 | 改 ontology.py 一处 |
| 加一个枚举值 | 改 Python list + 校验函数 + UI | 加一行 `xxx = PriorityValue("xxx")` |
| 改 Plan 必须 2 个 Task | 改 workflows.py 里的 if | 改一行 `min(2, Task)` |
| 语义是否机器可读 | 否（Python 字符串） | 是（OWL 公理，任何 DL 工具能加载） |
| 多份知识是否同步 | ❌ 靠人脑 | ✅ 公理之间语法上互相关联 |

---

## 一句话总结

**老写法把"业务形状"当成字符串和字典塞进程序，靠人脑维护多处一致性；**
**新写法把"业务形状"声明成 OWL 公理，靠语法和工具保证一致性。**

OWL 写法本身不依赖 Pellet（推理机）也能带来好处——比如 Pydantic schema、前端表单、
CI 校验脚本都可以从同一个本体文件派生，再也不会出现"本体改了某个字段，校验函数忘记改"
的尴尬。