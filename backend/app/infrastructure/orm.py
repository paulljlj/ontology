"""
这是 SQLAlchemy ORM 数据库实体模型
作用：定义 PostgreSQL 数据表结构，对应数据库真实表；
和你前面的 Pydantic BaseModel 区分：
    ORM 模型：后端 ↔ 数据库
    Pydantic 模型：后端 ↔ 前端
"""
from datetime import datetime
# 导入时间类型
from uuid import uuid4
# uuid4 用来生成全局唯一随机字符串ID

from sqlalchemy import DateTime, ForeignKey, String, Text, func
# 数据库字段类型：时间、外键、字符串、长文本；func代表数据库内置函数
from sqlalchemy.dialects.postgresql import JSONB
# PostgreSQL专用JSONB类型（支持索引、高效查询JSON内部字段）
from sqlalchemy.ext.mutable import MutableDict
# 可变字典包装，让SQLAlchemy识别字典修改并自动更新数据库
from sqlalchemy.orm import Mapped, mapped_column, relationship
# Mapped类型注解、字段定义、表关联关系
from sqlalchemy.types import JSON
# 通用JSON字段类型

from app.infrastructure.database import Base
# 数据库基础父类，所有数据表ORM都继承Base


# 生成主键ID工具函数
def new_id() -> str:
    return str(uuid4())
# uuid4生成随机唯一标识，转字符串；新建数据库记录时自动调用，作为主键id。
# 不使用数据库自增数字ID，方便分布式场景、前后端统一标识。


JsonType = JSON().with_variant(JSONB, "postgresql")
# 兼容多数据库JSON类型定义
# 当数据库是PostgreSQL，使用性能更强的JSONB（支持JSON内部字段索引、查询）；
# 其他数据库自动降级为标准JSON类型。


class OntologyClassORM(Base):
    # 【概念类型 数据库ORM模型，对应表 ontology_classes】
    __tablename__ = "ontology_classes"
    # 固定写法，指定该ORM映射到数据库中表名：ontology_classes

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    # 主键字段，字符串最大64位
    # mapped_column 是 SQLAlchemy 2.0 引入的函数，用来定义数据库列的所有属性。
    # primary_key=True：主键；default=new_id：程序创建对象时自动执行函数生成uuid，不需要数据库自增
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    # 概念类型名称，最多80字符
    # unique=True：整张表名称不能重复；index=True：建立索引，按name查询更快
    description: Mapped[str] = mapped_column(Text, default="")
    # 概念类型描述，Text长文本类型；不填写默认空字符串 ""，避免null
    schema: Mapped[dict] = mapped_column(MutableDict.as_mutable(JsonType), default=dict)
    # 存储该概念类型的属性约束模板（schema规则）
    # JsonType：JSON字段；MutableDict.as_mutable：让SQLAlchemy感知字典内部修改，自动更新数据库 
    # as_mutable 是 MutableDict 类提供的一个"转换器"类方法，
    # 它的作用是把普通的 JsonType 转换成"带变化监控功能的 JSON 类型"。
    # 否则只修改字典里面的一个属性时就不会通知数据库保存！！！
    # 数据库列的类型是 JSON
    # default=dict：新建记录默认空字典{}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 创建时间，带时区
    # server_default=func.now()：在【数据库层面】自动填入当前时间，不由后端代码传入时间

    instances: Mapped[list["OntologyInstanceORM"]] = relationship(back_populates="ontology_class")
    # ORM虚拟关联字段，**数据库表里不存在这一列**！
    # 一对多关系：一条概念类型，可以关联多条实例
    # back_populates 双向绑定：OntologyInstanceORM内的ontology_class
    # 作用：可以从子表查父表，可以从实例反推所属类


class OntologyInstanceORM(Base):          # 数据库ORM模型，对应知识图谱【实例】数据表
    __tablename__ = "ontology_instances"  #类 OntologyInstanceORM ↔ 数据库表 ontology_instances

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    class_id: Mapped[str] = mapped_column(ForeignKey("ontology_classes.id"), index=True)
    # 外键字段
    # ForeignKey("ontology_classes.id")：关联 ontology_classes 表的id
    # 作用：标记这条实例属于哪一个概念类型（Class）
    # index=True：建立索引，通过类别查询实例速度更快
    title: Mapped[str] = mapped_column(String(240), index=True)
    # 实例展示名称，最多240字符
    # index=True：支持根据名称快速检索实例
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    properties: Mapped[dict] = mapped_column(MutableDict.as_mutable(JsonType), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    # 更新时间
    # server_default=func.now()：新建记录自动填充初始时间
    # onupdate=func.now()：这条记录任意字段发生修改，数据库自动刷新该时间

    ontology_class: Mapped[OntologyClassORM] = relationship(back_populates="instances")
    # back_populates="instances" 和 OntologyClassORM中的instances双向配对
    # 开发便利：拿到实例对象 instance.ontology_class，直接获取所属概念类型信息，不用手写联表SQL


class OntologyRelationORM(Base):         # 知识图谱【关系边】数据库ORM模型，对应存储实例之间关联关系
    __tablename__ = "ontology_relations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("ontology_instances.id"), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("ontology_instances.id"), index=True)
    type: Mapped[str] = mapped_column(String(80), index=True)
    properties: Mapped[dict] = mapped_column(MutableDict.as_mutable(JsonType), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApprovalMappingORM(Base):
    """飞书审批实例 ↔ 本体 Spec 映射表，WebSocket 回调时按 instance_code 反查 Spec。"""
    __tablename__ = "approval_mappings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    spec_id: Mapped[str] = mapped_column(ForeignKey("ontology_instances.id"), index=True)
    instance_code: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="PENDING")  # PENDING / APPROVED / REJECTED
    approver_open_id: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
