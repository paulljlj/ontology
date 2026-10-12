"""OWL ontology for software-engineering artifacts and their constraints."""
from __future__ import annotations

import types
from pathlib import Path
from typing import Any

from owlready2 import (
    AllDifferent,
    AllDisjoint,
    AnnotationProperty,
    DatatypeProperty,
    FunctionalProperty,
    ObjectProperty,
    Thing,
    TransitiveProperty,
    get_ontology,
)
from owlready2.class_construct import EXACTLY, MIN, Restriction


ONTO_IRI = "http://ontology.local/engineering.owl"
DEFAULT_OWL_PATH = Path(__file__).with_name("engineering.owl")
onto = get_ontology(ONTO_IRI)


with onto:
    class instantiable(AnnotationProperty):
        pass

    class payload_field(AnnotationProperty):
        pass

    class payload_kind(AnnotationProperty):
        pass

    class EngineeringArtifact(Thing):
        pass

    class Requirement(EngineeringArtifact):
        pass

    class Specification(EngineeringArtifact):
        pass

    class Design(EngineeringArtifact):
        pass

    class Execution(EngineeringArtifact):
        pass

    class Log(Thing):
        pass

    class ControlledValue(Thing):
        pass

    class PriorityValue(ControlledValue):
        pass

    class LayerValue(ControlledValue):
        pass

    class Project(EngineeringArtifact):
        pass

    class Feature(Requirement):
        pass

    class Spec(Specification):
        pass

    class UserStory(Requirement):
        pass

    class Acceptance(Specification):
        pass

    class Clarification(Specification):
        pass

    class Plan(Design):
        pass

    class DataModel(Design):
        pass

    class Contract(Design):
        pass

    class ADR(Design):
        pass

    class Task(Execution):
        pass

    class Bug(Execution):
        pass

    class Checklist(Execution):
        pass

    class Reflection(Execution):
        pass

    class ExecutionLog(Log):
        pass

    class ServiceLog(Log):
        pass

    class JenkinsJob(Execution):
        pass

    class FeishuMessage(Execution):
        pass

    # 通用 Goal-to-Artifact 执行本体。具体数据报表只是首个能力实现，
    # 这些概念可以继续承载代码、文档、集成和运维等非固定场景。
    class Goal(Requirement):
        pass

    class Deliverable(Specification):
        pass

    class AcceptanceCriterion(Specification):
        pass

    class Capability(Design):
        pass

    class McpTool(Design):
        pass

    class SkillDefinition(Design):
        pass

    class SkillInstance(Execution):
        pass

    class WorkflowRun(Execution):
        pass

    class ExecutableTask(Execution):
        pass

    class Artifact(EngineeringArtifact):
        pass

    class Evidence(EngineeringArtifact):
        pass

    class Verification(Execution):
        pass

    class DeliveryBundle(EngineeringArtifact):
        pass

    class DataSource(EngineeringArtifact):
        pass

    class Dataset(EngineeringArtifact):
        pass

    class DataField(Design):
        pass

    class FieldMapping(Design):
        pass

    class DataQualityRule(Design):
        pass

    class MetricDefinition(Design):
        pass

    class ReportSpecification(Specification):
        pass


Project.instantiable = [True]
Project.comment = ["软件项目，是所有工程制品的根容器。"]

Feature.instantiable = [True]
Feature.comment = ["业务能力或技术改进。"]

Spec.instantiable = [True]
Spec.comment = ["需求规格说明。"]

UserStory.instantiable = [True]
UserStory.comment = ["面向角色和价值的用户故事。"]

Acceptance.instantiable = [True]
Acceptance.comment = ["验收标准。"]

Clarification.instantiable = [True]
Clarification.comment = ["需求澄清问题。"]

Plan.instantiable = [True]
Plan.comment = ["连接设计和任务的实现计划。"]

DataModel.instantiable = [True]
DataModel.comment = ["数据模型说明。"]

Contract.instantiable = [True]
Contract.comment = ["API、事件或工具契约。"]

ADR.instantiable = [True]
ADR.comment = ["架构决策记录。"]

Task.instantiable = [True]
Task.comment = ["可执行开发任务。"]

Bug.instantiable = [True]
Bug.comment = ["缺陷或回归。"]

Checklist.instantiable = [True]
Checklist.comment = ["质量门禁检查清单。"]

Reflection.instantiable = [True]
Reflection.comment = ["Agent 或人的复盘记录。"]

ExecutionLog.instantiable = [True]
ExecutionLog.comment = ["步骤执行日志。"]

ServiceLog.instantiable = [True]
ServiceLog.comment = ["服务运行日志。"]

JenkinsJob.instantiable = [True]
JenkinsJob.comment = ["CI/CD 构建任务。"]

FeishuMessage.instantiable = [True]
FeishuMessage.comment = ["飞书消息或回调。"]

_EXECUTION_CLASS_DESCRIPTIONS = {
    Goal: "用户希望系统实现的目标。",
    Deliverable: "需求约定的最终交付物。",
    AcceptanceCriterion: "判断结果是否满足需求的验收条件。",
    Capability: "与具体工具无关的抽象执行能力。",
    McpTool: "MCP 服务提供的可调用工具。",
    SkillDefinition: "组织一组能力与工具的可复用声明式 Skill。",
    SkillInstance: "针对一次需求动态编制的 Skill 实例。",
    WorkflowRun: "一次从需求到最终产物的完整执行。",
    ExecutableTask: "带输入、输出、依赖和验收条件的可执行 Task。",
    Artifact: "执行生成的代码、数据、表格、文档或外部结果。",
    Evidence: "测试、统计或日志形成的验证证据。",
    Verification: "对产物和验收条件进行的验证。",
    DeliveryBundle: "提供给用户的最终结果集合。",
    DataSource: "文件、数据库或外部服务等数据来源。",
    Dataset: "某一版本的结构化数据集合。",
    DataField: "数据集中的语义字段。",
    FieldMapping: "不同来源字段之间的语义映射。",
    DataQualityRule: "对数据完整性和一致性的检查规则。",
    MetricDefinition: "报表指标的计算定义。",
    ReportSpecification: "报表的维度、指标、结构和输出要求。",
}
for _execution_class, _description in _EXECUTION_CLASS_DESCRIPTIONS.items():
    _execution_class.instantiable = [True]
    _execution_class.comment = [_description]


AllDisjoint([EngineeringArtifact, Log, ControlledValue])
AllDisjoint([c for c in onto.classes() if getattr(c, "instantiable", [False]) and c.instantiable[0]])
AllDisjoint([PriorityValue, LayerValue])


with onto:
    low = PriorityValue("low")
    medium = PriorityValue("medium")
    high = PriorityValue("high")
    critical = PriorityValue("critical")

    domain = LayerValue("domain")
    application = LayerValue("application")
    api = LayerValue("api")
    infrastructure = LayerValue("infrastructure")
    test = LayerValue("test")

AllDifferent([low, medium, high, critical])
AllDifferent([domain, application, api, infrastructure, test])


def _define_data_field(name: str, value_type: type, kind: str):
    with onto:
        field = types.new_class(name, (DatatypeProperty, FunctionalProperty))
    field.domain = [Thing]
    field.range = [value_type]
    field.payload_field = [True]
    field.payload_kind = [kind]
    return field


# Field declarations for DatatypeProperty classes. This is structural data, not
# a "duplicate source of truth": Owlready2 requires each property to be its own
# class declaration (via types.new_class), and a dict-driven loop is the most
# maintainable way to declare 40+ properties without repeating boilerplate. Each
# entry maps a field name to (Python type, payload_kind) where payload_kind is
# the runtime serialization hint consumed by reasoner.py.
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

_FIELDS = {name: _define_data_field(name, value_type, kind) for name, (value_type, kind) in _FIELD_TYPES.items()}
globals().update(_FIELDS)


with onto:
    class priority(ObjectProperty, FunctionalProperty):
        pass

    class layer(ObjectProperty, FunctionalProperty):
        pass

priority.domain = [Thing]
priority.range = [PriorityValue]
priority.payload_field = [True]
priority.payload_kind = ["enum"]
layer.domain = [Thing]
layer.range = [LayerValue]
layer.payload_field = [True]
layer.payload_kind = ["enum"]


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


_constrain_fields(Project, required={"title": str}, optional={"status": str, "description": str, "storage": str})
_constrain_fields(
    Feature,
    required={"title": str},
    optional={"status": str, "description": str, "priority": PriorityValue, "source": str, "tags": str, "background": str},
)
_constrain_fields(
    Spec,
    required={"title": str, "goal": str},
    optional={"status": str, "version": str, "background": str, "clarifications": str, "ai_provider": str},
)
_constrain_fields(UserStory, required={"title": str, "body": str}, optional={"status": str})
_constrain_fields(Acceptance, required={"title": str, "rule": str}, optional={"status": str})
_constrain_fields(
    Clarification,
    required={"title": str},
    optional={"status": str, "question": str, "answer": str},
)
_constrain_fields(
    Plan,
    required={"title": str, "summary": str},
    optional={"status": str, "architecture": str},
)
_constrain_fields(DataModel, required={"title": str, "body": str}, optional={"status": str})
_constrain_fields(
    Contract,
    required={"title": str, "body": str},
    optional={"status": str, "method": str, "path": str},
)
_constrain_fields(
    ADR,
    required={"title": str, "decision": str},
    optional={"status": str, "context": str},
)
_constrain_fields(
    Task,
    required={"title": str, "layer": LayerValue},
    optional={"status": str, "definition_of_done": str, "estimate": str},
)
_constrain_fields(
    Checklist,
    required={"title": str},
    optional={"status": str, "passed": str, "failed": str, "checks": str},
)
_constrain_fields(
    Reflection,
    required={"title": str},
    optional={"status": str, "summary": str, "failed_checks": str},
)
_constrain_fields(
    JenkinsJob,
    required={"title": str},
    optional={"status": str, "environment": str, "result": str, "started_at": str, "finished_at": str, "build_number": int, "triggered_at": str, "mock": bool},
)
_constrain_fields(
    ExecutionLog,
    required={"title": str},
    optional={"status": str, "action": str, "target_instance_id": str, "duration_ms": int, "result": str, "summary": str, "message": str},
)
_constrain_fields(
    ServiceLog,
    required={"title": str},
    optional={"status": str, "service": str, "level": str, "message": str, "build_number": int, "mock": bool},
)
_constrain_fields(
    FeishuMessage,
    required={"title": str},
    optional={"status": str, "chat_id": str, "content": str, "sent_at": str},
)
_constrain_fields(
    Bug,
    required={"title": str},
    optional={"status": str, "severity": str, "repro_steps": str},
)

_constrain_fields(Goal, required={"title": str}, optional={"status": str, "goal": str, "description": str})
_constrain_fields(Deliverable, required={"title": str}, optional={"status": str, "description": str, "path": str})
_constrain_fields(AcceptanceCriterion, required={"title": str, "rule": str}, optional={"status": str})
_constrain_fields(Capability, required={"title": str}, optional={"description": str, "status": str})
_constrain_fields(McpTool, required={"title": str}, optional={"description": str, "method": str, "path": str, "status": str})
_constrain_fields(SkillDefinition, required={"title": str}, optional={"description": str, "body": str, "version": str, "status": str})
_constrain_fields(SkillInstance, required={"title": str}, optional={"description": str, "summary": str, "status": str})
_constrain_fields(WorkflowRun, required={"title": str}, optional={"goal": str, "status": str, "summary": str, "started_at": str, "finished_at": str, "result": str})
_constrain_fields(ExecutableTask, required={"title": str}, optional={"description": str, "status": str, "definition_of_done": str, "result": str})
_constrain_fields(Artifact, required={"title": str, "path": str}, optional={"status": str, "source": str, "result": str})
_constrain_fields(Evidence, required={"title": str, "body": str}, optional={"status": str, "source": str})
_constrain_fields(Verification, required={"title": str}, optional={"status": str, "passed": str, "failed": str, "checks": str})
_constrain_fields(DeliveryBundle, required={"title": str}, optional={"status": str, "summary": str, "path": str})
_constrain_fields(DataSource, required={"title": str}, optional={"status": str, "source": str, "path": str, "description": str})
_constrain_fields(Dataset, required={"title": str}, optional={"status": str, "source": str, "summary": str, "version": str})
_constrain_fields(DataField, required={"title": str}, optional={"description": str, "source": str})
_constrain_fields(FieldMapping, required={"title": str}, optional={"description": str, "source": str})
_constrain_fields(DataQualityRule, required={"title": str, "rule": str}, optional={"status": str, "severity": str})
_constrain_fields(MetricDefinition, required={"title": str, "rule": str}, optional={"description": str, "summary": str})
_constrain_fields(ReportSpecification, required={"title": str}, optional={"goal": str, "summary": str, "status": str})


with onto:
    class CONTAINS(ObjectProperty):
        pass

    CONTAINS.domain = [Thing]
    CONTAINS.range = [Thing]
    CONTAINS.comment = ["包含关系"]

    class DERIVES_TO(ObjectProperty, FunctionalProperty):
        pass

    DERIVES_TO.domain = [Feature]
    DERIVES_TO.range = [Spec]
    DERIVES_TO.comment = ["Feature 派生 Spec"]

    class HAS_STORY(ObjectProperty):
        pass

    HAS_STORY.domain = [Spec]
    HAS_STORY.range = [UserStory]
    HAS_STORY.comment = ["Spec 包含 UserStory"]

    class HAS_ACCEPTANCE(ObjectProperty):
        pass

    HAS_ACCEPTANCE.domain = [Spec]
    HAS_ACCEPTANCE.range = [Acceptance]
    HAS_ACCEPTANCE.comment = ["Spec 包含 Acceptance"]

    class HAS_PLAN(ObjectProperty):
        pass

    HAS_PLAN.domain = [Spec]
    HAS_PLAN.range = [Plan]
    HAS_PLAN.comment = ["Spec 包含 Plan"]

    class HAS_TASK(ObjectProperty):
        pass

    HAS_TASK.domain = [Plan]
    HAS_TASK.range = [Task]
    HAS_TASK.comment = ["Plan 包含 Task"]

    class HAS_CHECKLIST(ObjectProperty):
        pass

    HAS_CHECKLIST.domain = [EngineeringArtifact]
    HAS_CHECKLIST.range = [Checklist]
    HAS_CHECKLIST.comment = ["工程制品拥有 Checklist"]

    class HAS_REFLECTION(ObjectProperty):
        pass

    HAS_REFLECTION.domain = [EngineeringArtifact]
    HAS_REFLECTION.range = [Reflection]
    HAS_REFLECTION.comment = ["工程制品拥有 Reflection"]

    class IMPLEMENTS(ObjectProperty):
        pass

    IMPLEMENTS.domain = [Task]
    IMPLEMENTS.range = [Contract]
    IMPLEMENTS.comment = ["Task 实现 Contract"]

    class BLOCKED_BY(ObjectProperty, TransitiveProperty):
        pass

    BLOCKED_BY.domain = [Task]
    BLOCKED_BY.range = [Task]
    BLOCKED_BY.comment = ["Task 被另一个 Task 阻塞"]

    class TRIGGERS(ObjectProperty):
        pass

    TRIGGERS.domain = [Feature]
    TRIGGERS.range = [JenkinsJob]
    TRIGGERS.comment = ["Feature 触发 JenkinsJob"]

    class PRODUCES_LOG(ObjectProperty):
        pass

    PRODUCES_LOG.domain = [Thing]
    PRODUCES_LOG.range = [Log]
    PRODUCES_LOG.comment = ["节点产生日志"]

    class DECOMPOSES_TO(ObjectProperty):
        pass

    DECOMPOSES_TO.domain = [Goal]
    DECOMPOSES_TO.range = [ExecutableTask]
    DECOMPOSES_TO.comment = ["Goal 被拆解为可执行 Task"]

    class REQUIRES_CAPABILITY(ObjectProperty):
        pass

    REQUIRES_CAPABILITY.domain = [ExecutableTask]
    REQUIRES_CAPABILITY.range = [Capability]
    REQUIRES_CAPABILITY.comment = ["Task 需要抽象能力"]

    class IMPLEMENTED_BY(ObjectProperty):
        pass

    IMPLEMENTED_BY.domain = [Capability]
    IMPLEMENTED_BY.range = [SkillDefinition]
    IMPLEMENTED_BY.comment = ["Capability 由 Skill 实现"]

    class USES_TOOL(ObjectProperty):
        pass

    USES_TOOL.domain = [SkillInstance]
    USES_TOOL.range = [McpTool]
    USES_TOOL.comment = ["Skill 实例调用 MCP 工具"]

    class PRODUCES_ARTIFACT(ObjectProperty):
        pass

    PRODUCES_ARTIFACT.domain = [ExecutableTask]
    PRODUCES_ARTIFACT.range = [Artifact]
    PRODUCES_ARTIFACT.comment = ["Task 生成产物"]

    class VERIFIED_BY(ObjectProperty):
        pass

    VERIFIED_BY.domain = [Artifact]
    VERIFIED_BY.range = [Verification]
    VERIFIED_BY.comment = ["Artifact 由验证记录证明"]

    class HAS_EVIDENCE(ObjectProperty):
        pass

    HAS_EVIDENCE.domain = [Verification]
    HAS_EVIDENCE.range = [Evidence]
    HAS_EVIDENCE.comment = ["Verification 包含 Evidence"]

    class SATISFIES(ObjectProperty):
        pass

    SATISFIES.domain = [Artifact]
    SATISFIES.range = [AcceptanceCriterion]
    SATISFIES.comment = ["Artifact 满足验收条件"]

    class CONTAINS_ARTIFACT(ObjectProperty):
        pass

    CONTAINS_ARTIFACT.domain = [DeliveryBundle]
    CONTAINS_ARTIFACT.range = [Artifact]
    CONTAINS_ARTIFACT.comment = ["最终交付包包含产物"]


Plan.is_a.append(HAS_TASK.min(1, Task))



def _annotation_value(entity: Any, name: str, default: Any = None) -> Any:
    values = getattr(entity, name, [])
    return values[0] if values else default


def _class_restrictions(owl_class: type) -> list[Restriction]:
    restrictions: list[Restriction] = []
    for ancestor in owl_class.ancestors():
        restrictions.extend(item for item in ancestor.is_a if isinstance(item, Restriction))
    return restrictions


def get_class(name: str) -> type | None:
    entity = onto[name]
    if entity is None or not _annotation_value(entity, "instantiable", False):
        return None
    return entity


def list_classes() -> list[str]:
    return sorted(owl_class.name for owl_class in onto.classes() if _annotation_value(owl_class, "instantiable", False))


def list_relations() -> list[str]:
    return sorted(
        relation.name
        for relation in onto.object_properties()
        if not _annotation_value(relation, "payload_field", False)
    )


def get_schema(class_name: str) -> dict[str, Any]:
    owl_class = get_class(class_name)
    if owl_class is None:
        return {}

    fields: dict[str, dict[str, Any]] = {}
    for restriction in _class_restrictions(owl_class):
        field = restriction.property
        if not _annotation_value(field, "payload_field", False):
            continue
        details = fields.setdefault(
            field.name,
            {
                "required": False,
                "kind": _annotation_value(field, "payload_kind", "string"),
                "range": restriction.value,
            },
        )
        if restriction.type in (MIN, EXACTLY) and restriction.cardinality >= 1:
            details["required"] = True

    required_fields = sorted(name for name, details in fields.items() if details["required"])
    optional_fields = sorted(name for name, details in fields.items() if not details["required"])
    schema: dict[str, Any] = {
        "required_fields": required_fields,
        "optional_fields": optional_fields,
        "fields": fields,
        "description": _annotation_value(owl_class, "comment", ""),
    }
    for name, details in fields.items():
        if details["kind"] == "enum":
            schema[f"{name}_enum"] = sorted(instance.name for instance in details["range"].instances())
    return schema


def get_relation_schema(relation_name: str) -> dict[str, Any]:
    relation = onto[relation_name]
    if relation is None or relation_name not in list_relations():
        return {}
    return {
        "domain": [owl_class.name for owl_class in relation.domain],
        "range": [owl_class.name for owl_class in relation.range],
        "description": _annotation_value(relation, "comment", ""),
    }


def export_ontology(path: str | Path = DEFAULT_OWL_PATH) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    onto.save(file=str(destination), format="rdfxml")
    return destination
