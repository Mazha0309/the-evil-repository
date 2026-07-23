import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.models import EvidenceRelation, HypothesisStatus, ModelProvider, RunStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TaskCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,127}$")
    version: str = "1.0.0"
    name: str
    description: str
    category: str = "terminal"
    kind: str = "terminal"
    manifest: dict[str, Any]
    enabled: bool = True


class TaskRead(TaskCreate, ORMModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ModelCreate(BaseModel):
    name: str
    provider: ModelProvider
    base_url: HttpUrl
    model_id: str
    api_key: str | None = None
    native_tools: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ModelRead(ORMModel):
    id: uuid.UUID
    name: str
    provider: ModelProvider
    base_url: str
    model_id: str
    has_api_key: bool
    native_tools: bool
    parameters: dict[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class RunCreate(BaseModel):
    task_id: uuid.UUID
    candidate_model_id: uuid.UUID
    judge_model_id: uuid.UUID | None = None
    repetitions: int = Field(default=1, ge=1, le=5)
    temperature: float = Field(default=0, ge=0, le=2)
    soft_seconds: int = Field(default=5_400, ge=60, le=10_800)
    hard_seconds: int = Field(default=10_800, ge=300, le=21_600)
    soft_tool_calls: int = Field(default=500, ge=10, le=1_000)
    hard_tool_calls: int = Field(default=1_000, ge=20, le=2_000)


class RunRead(ORMModel):
    id: uuid.UUID
    task_id: uuid.UUID
    candidate_model_id: uuid.UUID
    judge_model_id: uuid.UUID | None
    status: RunStatus
    stage: str
    score: float | None
    scorecard: dict[str, Any]
    config: dict[str, Any]
    tool_calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class EventRead(ORMModel):
    id: int
    run_id: uuid.UUID
    sequence: int
    kind: str
    payload: dict[str, Any]
    created_at: datetime


class DashboardSummary(BaseModel):
    tasks: int
    models: int
    total_runs: int
    active_runs: int
    completed_runs: int
    average_score: float | None
    docker_ready: bool
    runner_enabled: bool


class HypothesisRead(ORMModel):
    id: uuid.UUID
    run_id: uuid.UUID
    key: str
    statement: str
    status: HypothesisStatus
    confidence: float
    next_action: str | None
    created_at: datetime
    updated_at: datetime


class HypothesisRevisionRead(ORMModel):
    id: int
    hypothesis_id: uuid.UUID
    sequence: int
    statement: str
    status: HypothesisStatus
    confidence: float
    next_action: str | None
    reason: str | None
    created_at: datetime


class EvidenceRead(ORMModel):
    id: uuid.UUID
    run_id: uuid.UUID
    key: str
    source_type: str
    source_ref: str
    summary: str
    trust: float
    content_hash: str | None
    created_at: datetime


class EvidenceEdgeRead(ORMModel):
    id: uuid.UUID
    run_id: uuid.UUID
    source_type: str
    source_key: str
    target_type: str
    target_key: str
    relation: EvidenceRelation
    weight: float
    explanation: str | None
    created_at: datetime


class InvestigationGraph(BaseModel):
    hypotheses: list[HypothesisRead]
    revisions: list[HypothesisRevisionRead]
    evidence: list[EvidenceRead]
    edges: list[EvidenceEdgeRead]
