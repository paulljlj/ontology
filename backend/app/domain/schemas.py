from datetime import datetime  # 导入时间类型，用于时间戳字段
from typing import Any         # 导入 Any 类型，表示任意类型的值

from pydantic import BaseModel, ConfigDict, Field
#BaseModel是Pydantic定义数据模型的基类，ConfigDict用于全局配置模型行为，Field为特定字段提供默认值、别名、校验等附加设置

# ！以下所有内容定义 API 接收什么数据、返回什么数据，以及数据长什么样

class OntologyClassRead(BaseModel):  #【描述返回给前端的 Ontology Class 数据结构】
    id: str    # 概念类型的唯一标识，如 "cls_project_001"，数据库主键，类型是字符串
    name: str  # 概念名称，如 "Project"，对应枚举 ClassName 中的值
    description: str  # 概念描述，如 "代表一个软件项目或产品"
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    #字段schema_接收字符串键、任意值的字典，默认生成空字典，外部传参可使用别名schema。
    created_at: datetime #创建时间字段，接收时间格式数据，Pydantic会自动转为datetime对象，才能对时间做运算、比较、格式化

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    #开启从类/ORM 对象读取数据——也就是可以直接访问对象id等，不用解包元组，同时支持别名和原字段名两种方式赋值。
    #model_config 是类层级属性，固定名称，不属于任何单个字段，Pydantic 读取它作为整个模型的统一配置，自然是全局规则。

class InstanceCreate(BaseModel): 
    class_id: str             #告诉系统这个实例属于哪个概念类型（Class），对应 OntologyClassRead.id
    title: str                #实例的标题/名称
    status: str = "draft"     #实例的状态， 默认值 "draft"（草稿），表示刚创建、未发布
    properties: dict[str, Any] = Field(default_factory=dict) 
    #存放实例的具体业务数据，格式由所属概念类型的 schema 约束， default_factory=dict 表示不传时默认为空字典 {}

class InstancePatch(BaseModel): # 【更新实例用的模型：PATCH请求，部分字段可传可不传】
    title: str | None = None    # title可以是字符串，也可以是None；不传数据默认值None，不传就不改原数据
    status: str | None = None   # status可以是字符串，也可以是None；不传数据默认值None
    properties: dict[str, Any] | None = None 
    # properties可以是{字符串:任意值}字典，也可以是None；不传默认None


class OntologyInstanceRead(BaseModel): # 【查询返回实例信息模型：读取数据返回前端】
    id: str           # id必须是字符串，没有默认值 → 必填字段，必须传入
    class_id: str     # class_id必须是字符串，必填
    class_name: str
    title: str        
    status: str
    properties: dict[str, Any] = Field(default_factory=dict) # properties：字符串key、任意值的字典；不传则自动生成空字典{}
    created_at: datetime   # 创建时间，接收时间字符串自动转为datetime对象，必填
    updated_at: datetime   # 更新时间，接收时间字符串自动转为datetime对象，必填

    model_config = ConfigDict(from_attributes=True) 
    # 模型全局配置：允许直接传入ORM数据库对象，无需手动转字典


class RelationCreate(BaseModel):   # 创建关系的数据模型，用于新增关系的POST接口，接收前端提交的数据
    source_id: str  # 源实例ID，字符串类型，必填；代表这条关系「从哪个实例出发」
    target_id: str  # 目标实例ID，字符串类型，必填；代表这条关系「指向哪个实例」
    type: str       # 关系类型，字符串类型，必填；例如 "belong_to"、"connect"，定义是什么样的关联
    properties: dict[str, Any] = Field(default_factory=dict)
    # 关系附带的自定义属性字典，key为字符串，值任意类型；前端不传时自动生成空字典{}，避免None引发报错


class OntologyRelationRead(BaseModel):  # 查询返回【关系】信息的模型，接口查询关系时，用来整理数据返回前端
    id: str          # 关系唯一编号，字符串类型，无默认值 → 必填，必须传入
    source_id: str   # 源实例ID，代表这条关系的起点节点
    target_id: str   # 目标实例ID，代表这条关系指向的终点节点
    type: str        # 关系类型标识，例如 belong_to、has_manager，用来区分是什么关联
    properties: dict[str, Any] = Field(default_factory=dict) # 关系附带扩展属性，字符串键、任意值字典；不传数据自动生成空字典{}，避免null引发代码报错
    inferred: bool = False  # 是否为推理得到的边（Pellet 一致性 / 传递闭包等）
    reason: str | None = None  # 推理原因描述，例如 transitive_closure
    created_at: datetime # 关系创建时间，Pydantic自动把时间字符串转为datetime时间对象，支持时间对比、运算，必填

    model_config = ConfigDict(from_attributes=True)  
    # 全局配置：允许直接传入数据库ORM对象，不用手动转为字典再解包

#GraphRead 是图谱打包容器：把【节点集合】和【关系集合】封装成一套标准结构，一次性返回给前端渲染图谱。
class GraphRead(BaseModel):            # 图谱整体返回模型，用于接口输出完整知识图谱数据给前端
    nodes: list[OntologyInstanceRead] 
    # 节点列表——名字随便起               # Pydantic 会自动把每条数据转换成 OntologyInstanceRead 模型
    # list[]：代表数组；列表里每一项都必须遵守 OntologyInstanceRead 结构（实例节点）
    # 无默认值 → 必填，接口一定会返回节点数组
    edges: list[OntologyRelationRead]
    # 边（关系）列表
    # list[]：代表数组；列表内每一条连线遵循 OntologyRelationRead 结构（实例之间的关系）

#前端想要查看某一条工作流特征，必须告诉后端：你要看哪一条。 如：GET /workflow/feature?feature_id=feat_001
class WorkflowFeatureRequest(BaseModel): # 请求模型：根据 feature_id 查询工作流特征
    feature_id: str
    # 特征唯一ID，字符串类型，无默认值 → 必填
    # 接口用来接收路径参数/请求参数，定位某一条工作流特征数据


class WorkflowSpecRequest(BaseModel):    # 请求模型：根据 spec_id 查询工作流规范定义
    spec_id: str
    # 工作流规范唯一ID，字符串，必填
    # 用来定位一套工作流基础定义模板


class WorkflowPlanRequest(BaseModel):   # 请求模型：根据 plan_id 查询工作流执行方案
    plan_id: str
    # 工作流方案唯一ID，字符串，必填
    # 定位一份具体的工作流执行计划


class ChecklistRequest(BaseModel):      # 请求模型：根据 root_id 查询清单树形数据
    root_id: str
    # 清单根节点ID，字符串，必填
    # 用来加载以该id为根的整套清单树结构

# Request 模型 = 前端传给后端的数据模板（入参）
# Read 模型 = 后端整理好传给前端的数据模板（出参）

class JenkinsTriggerRequest(BaseModel): # 触发Jenkins构建的入参模型
    job_id: str | None = None           # job_id：Jenkins任务ID，可以传字符串，也可以不传；不传默认None
    feature_id: str | None = None       # feature_id：工作流特征ID，可以传字符串，也可以不传；不传默认None
    environment: str = "staging"        # 部署环境，字符串类型；前端不传参数时，自动使用默认值 staging（预发环境）
# job_id: str | None = None             方式1：直接指定Jenkins任务ID启动构建
# feature_id: str | None = None         方式2：通过特征ID，后端自动找到对应的任务
# environment: str = "staging"          部署环境，没传默认预发staging
# 业务场景：
# 前端推送指令，告诉后端：启动一次构建，部署到哪个环境。
# 后端拿到这个模型里的参数，调用 Jenkins API 开始流水线。

class LogSearchRequest(BaseModel):      # 日志搜索查询的入参模型（查询条件，筛选日志）
    service: str | None = None          # service：服务名称，可选；不传代表不按服务过滤
    level: str | None = None            # level：日志级别（info/warn/error等），可选；不传代表不按级别过滤
    q: str | None = None                # q：搜索关键词，可选；不传代表不做全文关键词检索
# 规则：
# 前端不传某个字段 = 不启用这个过滤条件。
# 后端拿到模型参数，再拼数据库查询条件筛选日志。
