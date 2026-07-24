from __future__ import annotations

import hashlib
import importlib.util
import io
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
from app.telemetry import build_telemetry_bundle, json_bytes, jsonl_bytes
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
        telemetry = build_telemetry_bundle(result.events)
        event_data = jsonl_bytes(telemetry["events"])
        artifact_payloads = {
            name: value.encode() for name, value in result.artifacts.items()
        }
        investigation_graph = result.private_state.get(
            "investigation_graph",
            {
                "hypotheses": [],
                "revisions": [],
                "evidence": [],
                "edges": [],
            },
        )
        run_context = result.private_state.get("run_export", {})
        archive_readme = (
            "The Evil Repository run archive · schema v2\n\n"
            "run.json                         canonical manifest and integrity roots\n"
            "events.jsonl                     full timestamped immutable event stream\n"
            "telemetry/summary.json           derived latency, token, tool and error metrics\n"
            "telemetry/provider-turns.jsonl   one normalized row per model turn\n"
            "telemetry/tool-lifecycle.jsonl   paired tool call/result records\n"
            "telemetry/stage-timeline.jsonl   scenario and judge stage transitions\n"
            "telemetry/resource-snapshots.jsonl periodic Agent resource snapshots\n"
            "telemetry/errors.jsonl           Provider, tool, Runner and judge failures\n"
            "investigation/graph.json         hypotheses, revisions, evidence and edges\n"
            "artifacts/index.json             artifact size and SHA-256 inventory\n"
            "artifacts/*                      candidate and judge outputs\n\n"
            "Secrets and Provider credentials are excluded or redacted. This archive "
            "contains visible model output and tool I/O, never hidden chain-of-thought.\n"
        ).encode()
        artifact_inventory = [
            {
                "name": name,
                "archive_path": f"artifacts/{safe_archive_name(name)}",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            for name, payload in sorted(artifact_payloads.items())
        ]
        detailed_payloads = {
            "ARCHIVE_FORMAT.txt": archive_readme,
            "telemetry/summary.json": json_bytes(telemetry["summary"]),
            "telemetry/provider-turns.jsonl": jsonl_bytes(
                telemetry["provider_turns"]
            ),
            "telemetry/tool-lifecycle.jsonl": jsonl_bytes(
                telemetry["tool_lifecycle"]
            ),
            "telemetry/stage-timeline.jsonl": jsonl_bytes(
                telemetry["stage_timeline"]
            ),
            "telemetry/resource-snapshots.jsonl": jsonl_bytes(
                telemetry["resource_snapshots"]
            ),
            "telemetry/errors.jsonl": jsonl_bytes(telemetry["error_events"]),
            "investigation/graph.json": json_bytes(investigation_graph),
            "artifacts/index.json": json_bytes(artifact_inventory),
        }
        manifest = {
            "archive_schema_version": 2,
            "platform_version": VERSION,
            "scenario": prepared.metadata.model_dump(mode="json"),
            "run": run_context,
            "result": {
                "final_response": result.final_response,
                "elapsed_seconds": result.elapsed_seconds,
                "tool_calls": result.tool_calls,
                "artifacts": result.artifacts,
            },
            "telemetry_summary": telemetry["summary"],
            "artifact_inventory": artifact_inventory,
            "integrity": {
                "events_sha256": hashlib.sha256(event_data).hexdigest(),
                "artifact_sha256": {
                    name: hashlib.sha256(payload).hexdigest()
                    for name, payload in artifact_payloads.items()
                },
                "detail_entry_sha256": {
                    name: hashlib.sha256(payload).hexdigest()
                    for name, payload in detailed_payloads.items()
                },
            },
        }
        with tarfile.open(destination, "w:gz") as archive:
            add_archive_bytes(archive, "run.json", json_bytes(manifest))
            add_archive_bytes(archive, "events.jsonl", event_data)
            for name, payload in detailed_payloads.items():
                add_archive_bytes(archive, name, payload)
            for name, payload in artifact_payloads.items():
                add_archive_bytes(
                    archive,
                    f"artifacts/{safe_archive_name(name)}",
                    payload,
                )
        return destination

    def component_path(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if self.root.resolve() not in candidate.parents and candidate != self.root.resolve():
            raise ValueError(f"Scenario component escapes root: {relative}")
        return candidate


def safe_archive_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in value)


def add_archive_bytes(
    archive: tarfile.TarFile,
    name: str,
    payload: bytes,
) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o640
    archive.addfile(info, io.BytesIO(payload))


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
