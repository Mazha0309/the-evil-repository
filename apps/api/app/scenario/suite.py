"""Versioned benchmark-suite manifests.

A suite groups independent scenario families and public/held-out splits.  It
does not duplicate scenario packages and it refuses to claim leaderboard
readiness until the configured diversity thresholds are actually met.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, computed_field, model_validator

from app.scenario.sdk import ScenarioMetadata


class ScenarioSplit(StrEnum):
    development = "development"
    validation = "validation"
    held_out = "held_out"


class ScenarioFamilyStatus(StrEnum):
    active = "active"
    planned = "planned"
    retired = "retired"


class ScenarioFamily(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,127}$")
    name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    status: ScenarioFamilyStatus = ScenarioFamilyStatus.active


class SuiteScenarioReference(BaseModel):
    slug: str
    version: str
    family: str
    split: ScenarioSplit
    instances: int = Field(default=1, ge=1)
    weight: float = Field(default=1.0, gt=0)


class LeaderboardPolicy(BaseModel):
    minimum_active_families: int = Field(default=5, ge=1)
    minimum_held_out_families: int = Field(default=3, ge=1)
    minimum_scenarios: int = Field(default=20, ge=1)


class BenchmarkSuite(BaseModel):
    schema_version: int = Field(default=1, ge=1)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,127}$")
    version: str
    name: str
    description: str
    families: list[ScenarioFamily]
    scenarios: list[SuiteScenarioReference]
    leaderboard: LeaderboardPolicy = Field(default_factory=LeaderboardPolicy)
    localizations: dict[str, dict[str, str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_manifest(self) -> BenchmarkSuite:
        family_ids = [family.id for family in self.families]
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("Suite family IDs must be unique")
        scenario_keys = [
            (item.slug, item.version, item.split) for item in self.scenarios
        ]
        if len(scenario_keys) != len(set(scenario_keys)):
            raise ValueError("Suite scenario references must be unique per split")
        known = set(family_ids)
        for scenario in self.scenarios:
            if scenario.family not in known:
                raise ValueError(
                    f"Scenario {scenario.slug}@{scenario.version} references "
                    f"unknown family {scenario.family}"
                )
        return self

    @computed_field
    @property
    def readiness(self) -> dict[str, int | bool]:
        active = {
            family.id
            for family in self.families
            if family.status == ScenarioFamilyStatus.active
        }
        referenced = {item.family for item in self.scenarios}
        active_referenced = active & referenced
        held_out = {
            item.family
            for item in self.scenarios
            if item.split == ScenarioSplit.held_out and item.family in active
        }
        eligible = (
            len(active_referenced) >= self.leaderboard.minimum_active_families
            and len(held_out) >= self.leaderboard.minimum_held_out_families
            and len(self.scenarios) >= self.leaderboard.minimum_scenarios
        )
        return {
            "active_families": len(active_referenced),
            "held_out_families": len(held_out),
            "scenario_references": len(self.scenarios),
            "required_active_families": self.leaderboard.minimum_active_families,
            "required_held_out_families": self.leaderboard.minimum_held_out_families,
            "required_scenarios": self.leaderboard.minimum_scenarios,
            "leaderboard_eligible": eligible,
        }


def load_suite(path: Path, scenarios_root: Path | None = None) -> BenchmarkSuite:
    suite = BenchmarkSuite.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )
    if scenarios_root is not None:
        for reference in suite.scenarios:
            metadata_path = scenarios_root / reference.slug / "metadata.yaml"
            if not metadata_path.is_file():
                raise ValueError(
                    f"Suite references missing scenario {reference.slug}"
                )
            metadata = ScenarioMetadata.model_validate(
                yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
            )
            if metadata.version != reference.version:
                raise ValueError(
                    f"Suite expects {reference.slug}@{reference.version}, "
                    f"found {metadata.version}"
                )
    return suite


def load_suites(root: Path, scenarios_root: Path | None = None) -> list[BenchmarkSuite]:
    if not root.exists():
        return []
    return [
        load_suite(path, scenarios_root)
        for path in sorted(root.glob("*/suite.yaml"))
    ]
