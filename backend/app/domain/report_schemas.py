from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExecutionTaskRead(BaseModel):
    id: str
    task_key: str
    order_index: int
    title: str
    description: str
    status: str
    skill_spec: dict[str, Any] = Field(default_factory=dict)
    inputs: list[Any] = Field(default_factory=list)
    outputs: list[Any] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ArtifactRead(BaseModel):
    id: str
    task_id: str | None = None
    name: str
    kind: str
    mime_type: str
    size: int
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="artifact_metadata")
    created_at: datetime
    download_url: str = ""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class WorkflowRunRead(BaseModel):
    id: str
    workflow_type: str
    title: str
    requirement: str
    status: str
    result_contract: dict[str, Any] = Field(default_factory=dict)
    input_files: list[Any] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime
    tasks: list[ExecutionTaskRead] = Field(default_factory=list)
    artifacts: list[ArtifactRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
