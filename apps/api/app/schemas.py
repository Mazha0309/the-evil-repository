import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.model_parameters import validate_model_parameters
from app.models import (
    CredentialKind,
    CredentialStatus,
    EvidenceRelation,
    HypothesisStatus,
    ModelProvider,
    RunStatus,
    UserRole,
)
from app.run_outcomes import normalize_scorecard_outcome


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


class CredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: CredentialKind = CredentialKind.api_key
    secret: str = Field(min_length=1, max_length=65_536)


class CredentialImport(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: CredentialKind
    document: dict[str, Any]

    @model_validator(mode="after")
    def only_oauth_documents_are_imported(self) -> "CredentialImport":
        if self.kind == CredentialKind.api_key:
            raise ValueError("API keys must be created as a secret, not imported as JSON")
        return self


class CredentialUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)


class CredentialRead(ORMModel):
    id: uuid.UUID
    name: str
    kind: CredentialKind
    account_hint: str | None
    status: CredentialStatus
    expires_at: datetime | None
    last_refreshed_at: datetime | None
    last_validated_at: datetime | None
    last_error_code: str | None
    model_count: int = 0
    created_at: datetime
    updated_at: datetime


class OAuthDeviceStart(BaseModel):
    expires_at: datetime
    flow_token: str
    interval: int
    user_code: str
    verification_uri: str


class OAuthDevicePoll(BaseModel):
    flow_token: str = Field(min_length=1, max_length=16_384)
    name: str = Field(min_length=1, max_length=120)


class OAuthDevicePollResult(BaseModel):
    state: str
    credential: CredentialRead | None = None


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: ModelProvider
    base_url: HttpUrl
    model_id: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=8_192)
    credential_id: uuid.UUID | None = None
    native_tools: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("parameters")
    @classmethod
    def parameters_are_safe(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_model_parameters(value)

    @model_validator(mode="after")
    def one_credential_source(self) -> "ModelCreate":
        if self.credential_id is not None and self.api_key:
            raise ValueError("Choose either a saved credential or an inline API key")
        return self


class ModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    provider: ModelProvider | None = None
    base_url: HttpUrl | None = None
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=8_192)
    credential_id: uuid.UUID | None = None
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

    @model_validator(mode="after")
    def one_credential_source(self) -> "ModelUpdate":
        if (
            "credential_id" in self.model_fields_set
            and self.credential_id is not None
            and "api_key" in self.model_fields_set
            and self.api_key
        ):
            raise ValueError("Choose either a saved credential or an inline API key")
        return self


class ModelRead(ORMModel):
    id: uuid.UUID
    name: str
    provider: ModelProvider
    base_url: str
    model_id: str
    has_api_key: bool
    credential_id: uuid.UUID | None
    credential_name: str | None
    credential_kind: CredentialKind | None
    credential_status: CredentialStatus | None
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
    soft_seconds: int = Field(default=5_400, ge=60, le=14_400)
    hard_seconds: int = Field(default=10_800, ge=300, le=21_600)
    soft_tool_calls: int = Field(default=600, ge=10, le=2_000)
    hard_tool_calls: int = Field(default=2_200, ge=20, le=3_000)
    soft_provider_requests: int = Field(default=300, ge=1, le=5_000)
    hard_provider_requests: int = Field(default=720, ge=2, le=10_000)
    soft_total_tokens: int | None = Field(default=None, ge=1_000, le=1_000_000_000)
    hard_total_tokens: int | None = Field(default=None, ge=2_000, le=2_000_000_000)

    @model_validator(mode="after")
    def validate_budget_order(self) -> "RunCreate":
        if self.soft_seconds >= self.hard_seconds:
            raise ValueError("Soft time budget must be lower than the hard time budget")
        if self.soft_tool_calls >= self.hard_tool_calls:
            raise ValueError("Soft tool-call budget must be lower than the hard tool-call budget")
        if self.soft_provider_requests >= self.hard_provider_requests:
            raise ValueError(
                "Soft Provider-request budget must be lower than the hard "
                "Provider-request budget"
            )
        self._validate_optional_pair(
            "Token",
            self.soft_total_tokens,
            self.hard_total_tokens,
        )
        return self

    @staticmethod
    def _validate_optional_pair(
        label: str,
        soft: int | float | None,
        hard: int | float | None,
    ) -> None:
        if (soft is None) != (hard is None):
            raise ValueError(f"{label} soft and hard budgets must be configured together")
        if soft is not None and hard is not None and soft >= hard:
            raise ValueError(f"Soft {label.lower()} budget must be lower than the hard budget")


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

    @field_validator("scorecard", mode="before")
    @classmethod
    def infer_legacy_budget_outcome(cls, value: Any) -> dict[str, Any]:
        return normalize_scorecard_outcome(value)


class RunArtifactRead(ORMModel):
    id: uuid.UUID
    run_id: uuid.UUID
    name: str
    media_type: str
    sha256: str
    size: int
    metadata_json: dict[str, Any]
    created_at: datetime


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
