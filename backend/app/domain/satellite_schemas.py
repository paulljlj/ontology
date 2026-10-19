"""Stable integration contract for the independently developed diagnosis module."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(min_length=1, max_length=180)
    object_id: str = Field(min_length=1, max_length=180)
    timestamp: datetime
    available_at: datetime
    source_file: str = Field(pattern=r"^observed/[a-z_]+\.csv$")
    record_id: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=1000)

    @field_validator("timestamp", "available_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("时间必须包含时区")
        return value


class CauseCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_id: str = Field(min_length=1, max_length=180)
    object_type: Literal["satellite", "ground_station", "link"]
    mechanism: str = Field(min_length=1, max_length=240)
    status: Literal["candidate", "supported", "insufficient_evidence"] = "candidate"
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=200)
    contradicting_evidence_ids: list[str] = Field(default_factory=list, max_length=200)
    missing_evidence: list[str] = Field(default_factory=list, max_length=100)


class DiagnosisInput(BaseModel):
    """A collaborator supplies this JSON; no executable code or file paths."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(pattern=r"^CASE-\d{3,12}$")
    analysis_start: datetime
    analysis_end: datetime
    as_of: datetime
    source: Literal["external_diagnosis", "development_fixture"] = "external_diagnosis"
    overview: dict[str, Any] = Field(default_factory=dict)
    causes: list[CauseCandidate] = Field(default_factory=list, max_length=100)
    watch_items: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    impact: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    conclusions: list[str] = Field(default_factory=list, max_length=100)
    missing_evidence: list[str] = Field(default_factory=list, max_length=100)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=2000)

    @field_validator("analysis_start", "analysis_end", "as_of")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("时间必须包含时区")
        return value

    @model_validator(mode="after")
    def check_evidence(self):
        if not self.analysis_start < self.analysis_end <= self.as_of:
            raise ValueError("应满足分析开始 < 分析结束 <= 证据截止时间")
        ids = [e.evidence_id for e in self.evidence]
        if len(set(ids)) != len(ids):
            raise ValueError("evidence_id不能重复")
        if any(e.available_at > self.as_of or e.timestamp > self.as_of for e in self.evidence):
            raise ValueError("诊断证据不能包含截止时间之后的信息")
        known = set(ids)
        for cause in self.causes:
            if not set(cause.supporting_evidence_ids + cause.contradicting_evidence_ids) <= known:
                raise ValueError("候选引用了不存在的证据ID")
            if cause.status == "supported" and not cause.supporting_evidence_ids:
                raise ValueError("标记supported的候选必须有支持证据")
        return self


class SatelliteRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(pattern=r"^CASE-\d{3,12}$")
    avoid_objects: list[str] = Field(default_factory=list, max_length=100)
    service_ids: list[str] | None = Field(default=None, max_length=100)
    at: datetime | None = None
    as_of: datetime | None = None
    requirement: str = Field(default="检查指定对象的备选通信路径，验算容量与时延，并保留证据。", max_length=4000)
    max_utilization_pct: float = Field(default=85, gt=0, le=100, allow_inf_nan=False)
    max_latency_ms: float = Field(default=150, gt=0, le=10000, allow_inf_nan=False)
    max_options: int = Field(default=3, ge=1, le=5)
    diagnosis: DiagnosisInput | None = None

    @field_validator("at", "as_of")
    @classmethod
    def aware(cls, value: datetime | None):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("时间必须包含时区")
        return value

    @field_validator("avoid_objects", "service_ids")
    @classmethod
    def identifiers(cls, values: list[str] | None):
        import re
        if values is None:
            return values
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", v) for v in values):
            raise ValueError("对象ID格式不合法")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def matching_diagnosis(self):
        if self.at and self.as_of and self.at > self.as_of:
            raise ValueError("快照不能晚于证据截止时间")
        if self.diagnosis and self.diagnosis.case_id != self.case_id:
            raise ValueError("诊断结果与所选案例不一致")
        if self.diagnosis and self.as_of and self.diagnosis.as_of > self.as_of:
            raise ValueError("诊断结果使用了本次截止时间之后的信息")
        if not self.avoid_objects and self.diagnosis:
            self.avoid_objects = [c.object_id for c in self.diagnosis.causes if c.status == "supported"]
        if not self.avoid_objects:
            raise ValueError("请指定待避对象，或提供有证据支持的诊断候选；系统不会猜测同学的诊断结果")
        return self
