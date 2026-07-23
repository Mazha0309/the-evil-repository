import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.model_parameters import validate_model_parameters
from app.models import EvidenceRelation, HypothesisStatus, ModelProvider, RunStatus, UserRole


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AuthConfig(BaseModel):
    setup_required: bool
    registration_enabled: bool
    setup_token_required: bool
    version: str


class LoginCreate(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=1, max_length=256)


class SetupCreate(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=8, max_length=256)
    setup_token: str | None = Field(default=None, max_length=500)


class RegisterCreate(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=8, max_length=256)


class UserRead(ORMModel):
    id: uuid.UUID
    username: str
    role: UserRole
    enabled: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AuthRead(BaseModel):
    user: UserRead
    csrf_token: str
    expires_at: datetime


class AccountUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=32)
    current_password: str | None = Field(default=None, max_length=256)
    new_password: str | None = Field(default=None, min_length=8, max_length=256)


class SessionRead(ORMModel):
    id: uuid.UUID
    expires_at: datetime
    user_agent: str | None
    ip_address: str | None
    created_at: datetime
    last_seen_at: datetime
    current: bool = False


class AdminUserCreate(RegisterCreate):
    role: UserRole = UserRole.user
    enabled: bool = True


class AdminUserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=32)
    role: UserRole | None = None
    enabled: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)


class PlatformSettingsRead(ORMModel):
    registration_enabled: bool
    runner_concurrency: int
    updated_by: uuid.UUID | None
    updated_at: datetime


class PlatformSettingsUpdate(BaseModel):
    registration_enabled: bool | None = None
    runner_concurrency: int | None = Field(default=None, ge=1, le=16)


class AdminSummary(BaseModel):
    users: int
    enabled_users: int
    admins: int
    models: int
    total_runs: int
    active_runs: int


class ServerMonitor(BaseModel):
    observed_at: datetime
    api: dict[str, Any]
    runner: dict[str, Any]
    database: dict[str, Any]
    queue: dict[str, Any]


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
    name: str = Field(min_length=1, max_length=120)
    provider: ModelProvider
    base_url: HttpUrl
    model_id: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=8_192)
    native_tools: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("parameters")
    @classmethod
    def parameters_are_safe(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_model_parameters(value)


class ModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    provider: ModelProvider | None = None
    base_url: HttpUrl | None = None
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=8_192)
    native_tools: bool | None = None
    parameters: dict[str, Any] | None = None
    enabled: bool | None = None

    @field_validator("parameters")
    @classmethod
    def parameters_are_safe(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        return validate_model_parameters(value) if value is not None else None


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
    instance_seed: int | None = Field(default=None, ge=1, le=2_147_483_647)
    soft_seconds: int = Field(default=2_400, ge=60, le=14_400)
    hard_seconds: int = Field(default=4_800, ge=300, le=21_600)
    soft_tool_calls: int = Field(default=1_200, ge=10, le=2_000)
    hard_tool_calls: int = Field(default=2_200, ge=20, le=3_000)


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
