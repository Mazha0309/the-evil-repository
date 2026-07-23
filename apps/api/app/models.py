import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def now_utc() -> datetime:
    return datetime.now(UTC)


class ModelProvider(StrEnum):
    openai_compatible = "openai_compatible"
    ollama = "ollama"


class RunStatus(StrEnum):
    queued = "queued"
    preparing = "preparing"
    running = "running"
    scoring = "scoring"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class HypothesisStatus(StrEnum):
    proposed = "proposed"
    testing = "testing"
    supported = "supported"
    rejected = "rejected"
    confirmed = "confirmed"


class EvidenceRelation(StrEnum):
    supports = "supports"
    contradicts = "contradicts"
    derived_from = "derived_from"
    supersedes = "supersedes"
    corroborates = "corroborates"


class RunnerHeartbeat(Base):
    __tablename__ = "runner_heartbeats"

    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    docker_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class TaskDefinition(Base):
    __tablename__ = "task_definitions"
    __table_args__ = (UniqueConstraint("slug", "version", name="uq_task_slug_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="terminal")
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class ModelProfile(Base):
    __tablename__ = "model_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    provider: Mapped[ModelProvider] = mapped_column(Enum(ModelProvider))
    base_url: Mapped[str] = mapped_column(String(500))
    model_id: Mapped[str] = mapped_column(String(200))
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    native_tools: Mapped[bool] = mapped_column(Boolean, default=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task_definitions.id"), index=True)
    candidate_model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_profiles.id"), index=True)
    judge_model_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_profiles.id"), nullable=True)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.queued, index=True)
    stage: Mapped[str] = mapped_column(String(120), default="Queued")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    scorecard: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_event_run_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("benchmark_runs.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class RunArtifact(Base):
    __tablename__ = "run_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("benchmark_runs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    media_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    path: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    __table_args__ = (UniqueConstraint("run_id", "key", name="uq_hypothesis_run_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("benchmark_runs.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(80))
    statement: Mapped[str] = mapped_column(Text)
    status: Mapped[HypothesisStatus] = mapped_column(Enum(HypothesisStatus))
    confidence: Mapped[float] = mapped_column(Float)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class HypothesisRevision(Base):
    __tablename__ = "hypothesis_revisions"
    __table_args__ = (UniqueConstraint("hypothesis_id", "sequence", name="uq_hypothesis_revision_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hypothesis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hypotheses.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    statement: Mapped[str] = mapped_column(Text)
    status: Mapped[HypothesisStatus] = mapped_column(Enum(HypothesisStatus))
    confidence: Mapped[float] = mapped_column(Float)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("run_id", "key", name="uq_evidence_run_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("benchmark_runs.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(80))
    source_type: Mapped[str] = mapped_column(String(80))
    source_ref: Mapped[str] = mapped_column(String(1000))
    summary: Mapped[str] = mapped_column(Text)
    trust: Mapped[float] = mapped_column(Float)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class EvidenceEdge(Base):
    __tablename__ = "evidence_edges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("benchmark_runs.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(40))
    source_key: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str] = mapped_column(String(40))
    target_key: Mapped[str] = mapped_column(String(80))
    relation: Mapped[EvidenceRelation] = mapped_column(Enum(EvidenceRelation))
    weight: Mapped[float] = mapped_column(Float, default=1)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
