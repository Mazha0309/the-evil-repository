from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tarfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, Field

from app.challenge.spec import BudgetSpec, RepositorySpec
from app.runner.protocol import ToolResult
from app.version import VERSION

if TYPE_CHECKING:
    from app.runner.sandbox import DockerSandbox


class ScenarioComponents(BaseModel):
    repositories: str
    database: dict[str, str] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)
    grading: dict[str, str]
    mirror: str = "mirror/"


class ContextPressure(BaseModel):
    target_files: int
    target_git_commits: int
    target_mirror_bytes: int
    repeated_read_penalty_after: int = 2
    native_context_window: bool = True
    reference_solve_minutes: int = 80


class CalibrationPolicy(BaseModel):
    """Defines which completed runs may inform future budget calibration."""

    minimum_success_score: int = Field(default=900, ge=0)
    require_completion_contract: bool = True
    require_hidden_verification: bool = True
    exclude_budget_exhausted: bool = True


class CompletionRequirements(BaseModel):
    min_tool_calls: int = 0
    min_hypotheses: int = 0
    min_rejected_hypotheses: int = 0
    min_evidence: int = 0
    required_evidence_sources: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    required_artifacts: dict[str, int] = Field(default_factory=dict)


class IncidentRequirements(BaseModel):
    """Public incident-simulation contract.

    The schedule and correct dispositions stay in ``PreparedScenario.private_state``.
    This model only tells a candidate which investigation coverage is required.
    """

    enabled: bool = False
    logical_tick_seconds: int = 60
    horizon_ticks: int = 180
    min_logical_ticks: int = 0
    min_unique_observations: int = 0
    min_services_observed: int = 0
    phase_observations: dict[str, int] = Field(default_factory=dict)
    required_decisions: list[str] = Field(default_factory=list)
    require_snapshot_before_risky_action: bool = True
    required_verification_modes: list[str] = Field(default_factory=list)
    required_successful_verification_modes: list[str] = Field(default_factory=list)
    required_verification_sequence: list[str] = Field(default_factory=list)


class ReleaseRequirements(BaseModel):
    """Public contract for a deterministic software-release replay.

    Artifact identities, trusted roots and acceptable recovery digests stay in
    ``PreparedScenario.private_state``.  The manifest only exposes the amount
    of investigation and recovery coverage required before a final answer.
    """

    enabled: bool = False
    logical_tick_seconds: int = 60
    horizon_ticks: int = 120
    min_logical_ticks: int = 0
    min_unique_observations: int = 0
    required_decisions: list[str] = Field(default_factory=list)
    require_snapshot_before_irreversible: bool = True
    require_containment: bool = True
    required_verification_modes: list[str] = Field(default_factory=list)
    required_successful_verification_modes: list[str] = Field(default_factory=list)
    required_verification_sequence: list[str] = Field(default_factory=list)


class ScenarioMetadata(BaseModel):
    slug: str
    version: str
    name: str
    sdk_version: int = 1
    entrypoint: str
    description: str
    seed: int
    opening_prompt: str
    repositories: list[RepositorySpec]
    budget: BudgetSpec
    tools: list[str]
    components: ScenarioComponents
    context_pressure: ContextPressure
    calibration: CalibrationPolicy = Field(default_factory=CalibrationPolicy)
    completion: CompletionRequirements = Field(default_factory=CompletionRequirements)
    incident: IncidentRequirements = Field(default_factory=IncidentRequirements)
    release: ReleaseRequirements = Field(default_factory=ReleaseRequirements)
    scoring: dict[str, int]
    localizations: dict[str, dict[str, str]] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass
class PreparedScenario:
    scenario_root: Path
    workspace: Path
    metadata: ScenarioMetadata
    browser_index: Path | None = None
    private_state: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScenarioRunResult:
    final_response: str
    elapsed_seconds: float
    tool_calls: int
    events: list[dict[str, Any]]
    artifacts: dict[str, str] = field(default_factory=dict)
    private_state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScenarioCheck:
    """One trusted, scenario-owned hidden verification phase."""

    key: str
    label: str
    execute: Callable[[], ToolResult]


class Scenario(ABC):
    """Trusted host-side plugin. Scenario code is never copied into a candidate sandbox."""

    def __init__(self, root: Path, metadata: ScenarioMetadata) -> None:
        self.root = root
        self.metadata = metadata

    @classmethod
    def load(cls, root: Path) -> Scenario:
        return load_scenario(root)

    @abstractmethod
    def prepare(
        self,
        output: Path,
        *,
        scale: float = 1.0,
        instance_seed: int | None = None,
    ) -> PreparedScenario:
        """Build an isolated, deterministic candidate workspace."""

    def run(
        self,
        prepared: PreparedScenario,
        executor: Callable[[PreparedScenario], ScenarioRunResult],
    ) -> ScenarioRunResult:
        """Run through an injected executor so the SDK stays provider-agnostic."""
        return executor(prepared)

    @abstractmethod
    def collect_artifacts(
        self,
        prepared: PreparedScenario,
        result: ScenarioRunResult,
        sandbox: DockerSandbox,
    ) -> None:
        """Collect scenario-specific candidate outputs before hidden grading."""

    def verification_checks(
        self,
        prepared: PreparedScenario,
        result: ScenarioRunResult,
        sandbox: DockerSandbox,
    ) -> list[ScenarioCheck]:
        """Return trusted checks without coupling Worker to repository names."""
        return []

    @abstractmethod
    def grade(
        self,
        prepared: PreparedScenario,
        result: ScenarioRunResult,
    ) -> dict[str, Any]:
        """Execute hidden, host-side grading phases."""

    def archive(
        self,
        prepared: PreparedScenario,
        result: ScenarioRunResult,
        destination: Path,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        event_data = (
            "\n".join(
                json.dumps(event, ensure_ascii=False, sort_keys=True)
                for event in result.events
            )
            + ("\n" if result.events else "")
        ).encode()
        artifact_payloads = {
            name: value.encode() for name, value in result.artifacts.items()
        }
        manifest = {
            "platform_version": VERSION,
            "scenario": prepared.metadata.model_dump(mode="json"),
            "result": {
                "final_response": result.final_response,
                "elapsed_seconds": result.elapsed_seconds,
                "tool_calls": result.tool_calls,
                "artifacts": result.artifacts,
            },
            "integrity": {
                "events_sha256": hashlib.sha256(event_data).hexdigest(),
                "artifact_sha256": {
                    name: hashlib.sha256(payload).hexdigest()
                    for name, payload in artifact_payloads.items()
                },
            },
        }
        with tarfile.open(destination, "w:gz") as archive:
            data = json.dumps(manifest, indent=2, ensure_ascii=False).encode()
            info = tarfile.TarInfo("run.json")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
            event_info = tarfile.TarInfo("events.jsonl")
            event_info.size = len(event_data)
            archive.addfile(event_info, io.BytesIO(event_data))
            for name, payload in artifact_payloads.items():
                artifact_info = tarfile.TarInfo(f"artifacts/{safe_archive_name(name)}")
                artifact_info.size = len(payload)
                archive.addfile(artifact_info, io.BytesIO(payload))
        return destination

    def component_path(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if self.root.resolve() not in candidate.parents and candidate != self.root.resolve():
            raise ValueError(f"Scenario component escapes root: {relative}")
        return candidate


def safe_archive_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in value)


def load_scenario(root: Path) -> Scenario:
    root = root.resolve()
    metadata_path = root / "metadata.yaml"
    metadata = ScenarioMetadata.model_validate(yaml.safe_load(metadata_path.read_text(encoding="utf-8")))
    module_name, class_name = metadata.entrypoint.split(":", 1)
    module_path = root / module_name
    digest = hashlib.sha256(str(module_path).encode()).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(f"evil_scenario_{digest}", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load scenario entrypoint: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    implementation = getattr(module, class_name)
    if not issubclass(implementation, Scenario):
        raise TypeError(f"{class_name} must extend Scenario")
    return implementation(root, metadata)


def load_component_module(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
