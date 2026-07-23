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
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.challenge.spec import BudgetSpec, RepositorySpec


class ScenarioComponents(BaseModel):
    repositories: str
    database: dict[str, str]
    failures: list[str]
    grading: dict[str, str]
    mirror: str


class ContextPressure(BaseModel):
    target_files: int
    target_git_commits: int
    target_mirror_bytes: int
    repeated_read_penalty_after: int = 2
    native_context_window: bool = True


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


class Scenario(ABC):
    """Trusted host-side plugin. Scenario code is never copied into a candidate sandbox."""

    def __init__(self, root: Path, metadata: ScenarioMetadata) -> None:
        self.root = root
        self.metadata = metadata

    @classmethod
    def load(cls, root: Path) -> "Scenario":
        return load_scenario(root)

    @abstractmethod
    def prepare(self, output: Path, *, scale: float = 1.0) -> PreparedScenario:
        """Build an isolated, deterministic candidate workspace."""

    def run(
        self,
        prepared: PreparedScenario,
        executor: Callable[[PreparedScenario], ScenarioRunResult],
    ) -> ScenarioRunResult:
        """Run through an injected executor so the SDK stays provider-agnostic."""
        return executor(prepared)

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
        manifest = {
            "scenario": self.metadata.model_dump(mode="json"),
            "result": {
                "final_response": result.final_response,
                "elapsed_seconds": result.elapsed_seconds,
                "tool_calls": result.tool_calls,
                "artifacts": result.artifacts,
            },
        }
        with tarfile.open(destination, "w:gz") as archive:
            data = json.dumps(manifest, indent=2, ensure_ascii=False).encode()
            info = tarfile.TarInfo("run.json")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
            for name, value in result.artifacts.items():
                payload = value.encode()
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
