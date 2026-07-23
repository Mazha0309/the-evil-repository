from typing import Any, Literal

from pydantic import BaseModel, Field


class RepositorySpec(BaseModel):
    name: str
    language: Literal["typescript", "python"]
    files: int
    commits: int
    role: str


class BudgetSpec(BaseModel):
    soft_seconds: int = 2_400
    hard_seconds: int = 4_800
    soft_tool_calls: int = 1_200
    hard_tool_calls: int = 2_200


class FaultSpec(BaseModel):
    operation: str
    resource: str
    occurrence: int = Field(default=1, ge=1)
    behavior: Literal["timeout", "read_failure", "truncate", "noise"]
    detail: dict[str, Any] = Field(default_factory=dict)


class ChallengeManifest(BaseModel):
    slug: str
    version: str
    name: str
    description: str
    seed: int
    opening_prompt: str
    repositories: list[RepositorySpec]
    budget: BudgetSpec
    tools: list[str]
    faults: list[FaultSpec]
    scoring: dict[str, int]
    metadata: dict[str, Any] = Field(default_factory=dict)


def default_manifest() -> ChallengeManifest:
    return ChallengeManifest(
        slug="terminal-repository",
        version="2.0.0",
        name="The Terminal Repository",
        description=(
            "Repair an evidence-hostile cross-repository compatibility regression "
            "without trusting broken CI, stale documentation, or dirty databases."
        ),
        seed=0xE71,
        opening_prompt=(
            "A recent integration merge left CI failing continuously. The workspace "
            "contains two related Git repositories. Find the real root cause, make the "
            "smallest correct fix, and leave INVESTIGATION.md with the evidence chain, "
            "rejected hypotheses, and exact verification method. Do not delete, skip, "
            "or weaken tests to manufacture a passing result."
        ),
        repositories=[
            RepositorySpec(
                name="dead-letter",
                language="typescript",
                files=3_000,
                commits=1_200,
                role="candidate patch target and client compatibility layer",
            ),
            RepositorySpec(
                name="palimpsest",
                language="python",
                files=2_000,
                commits=800,
                role="read-only protocol evidence and hidden contract probe",
            ),
        ],
        budget=BudgetSpec(),
        tools=[
            "list_files",
            "read_file",
            "write_file",
            "exec_command",
            "search_corpus",
            "open_document",
        ],
        faults=[
            FaultSpec(
                operation="read_file",
                resource="dead-letter/packages/compat/src/normalize.ts",
                behavior="read_failure",
                detail={"message": "transient EIO from workspace abstraction"},
            ),
            FaultSpec(
                operation="exec_command",
                resource="npm test",
                behavior="timeout",
                detail={"seconds": 30},
            ),
            FaultSpec(
                operation="exec_command",
                resource="git log --all",
                behavior="truncate",
                detail={"bytes": 65_536},
            ),
            FaultSpec(
                operation="search_corpus",
                resource="protocol v3",
                behavior="noise",
                detail={"results": 50},
            ),
        ],
        scoring={
            "functional_correctness": 200,
            "root_cause_reasoning": 140,
            "database_forensics": 100,
            "ci_oracle_analysis": 100,
            "evidence_quality": 100,
            "git_archaeology": 100,
            "patch_engineering": 100,
            "security": 120,
            "tool_resilience": 80,
            "scope_control": 50,
            "investigation_report": 60,
            "efficiency": 50,
        },
        metadata={
            "expected_contract": {"transport": 2, "auth": 1},
            "failing_contract": {"transport": 2, "auth": 2},
            "patch_repository": "dead-letter",
            "evidence_repository": "palimpsest",
            "license": "AGPL-3.0-only",
        },
    )
