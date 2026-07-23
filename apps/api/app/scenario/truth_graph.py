"""Private truth-graph contracts and deterministic multi-path evaluation.

Truth graphs belong to the trusted grading boundary.  A scenario may expose a
redacted shape or aggregate result, but node labels, accepted paths and hidden
checks must never be copied into the candidate workspace.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class TruthNodeKind(StrEnum):
    cause = "cause"
    condition = "condition"
    symptom = "symptom"
    constraint = "constraint"
    invariant = "invariant"
    remediation = "remediation"


class TruthEdgeRelation(StrEnum):
    causes = "causes"
    enables = "enables"
    explains = "explains"
    constrains = "constrains"
    contradicts = "contradicts"
    mitigates = "mitigates"
    verifies = "verifies"


class TruthNode(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")
    kind: TruthNodeKind
    label: str
    weight: float = Field(default=1.0, gt=0, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TruthEdge(BaseModel):
    source: str
    target: str
    relation: TruthEdgeRelation


class ResolutionPath(BaseModel):
    """One acceptable engineering resolution.

    ``required_nodes`` are conjunctive.  Every entry in ``any_of_nodes`` is a
    disjunctive group, so at least one node from each group must be observed.
    Hidden checks are objective judge outputs rather than candidate claims.
    """

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")
    label: str
    required_nodes: list[str] = Field(default_factory=list)
    any_of_nodes: list[list[str]] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=list)


class TruthGraph(BaseModel):
    schema_version: int = Field(default=1, ge=1)
    nodes: list[TruthNode]
    edges: list[TruthEdge] = Field(default_factory=list)
    acceptable_paths: list[ResolutionPath]
    minimum_causal_coverage: float = Field(default=0.6, ge=0, le=1)

    @model_validator(mode="after")
    def validate_references(self) -> TruthGraph:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Truth graph node IDs must be unique")
        path_ids = [path.id for path in self.acceptable_paths]
        if len(path_ids) != len(set(path_ids)):
            raise ValueError("Truth graph path IDs must be unique")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError(
                    f"Truth graph edge references unknown node: "
                    f"{edge.source} -> {edge.target}"
                )
        for path in self.acceptable_paths:
            references = set(path.required_nodes)
            references.update(
                node_id
                for alternatives in path.any_of_nodes
                for node_id in alternatives
            )
            unknown = references - known
            if unknown:
                raise ValueError(
                    f"Resolution path {path.id} references unknown nodes: "
                    + ", ".join(sorted(unknown))
                )
            if any(not alternatives for alternatives in path.any_of_nodes):
                raise ValueError(
                    f"Resolution path {path.id} contains an empty alternative group"
                )
        if not self.acceptable_paths:
            raise ValueError("Truth graph requires at least one acceptable path")
        return self


class ResolutionPathResult(BaseModel):
    path_id: str
    coverage: float
    satisfied: bool
    missing_nodes: list[str]
    missing_alternative_groups: list[list[str]]
    failed_checks: list[str]


class TruthGraphEvaluation(BaseModel):
    accepted: bool
    causal_coverage: float
    best_path_coverage: float
    partial_credit: float
    satisfied_paths: list[str]
    observed_nodes: list[str]
    paths: list[ResolutionPathResult]


def evaluate_truth_graph(
    graph: TruthGraph,
    *,
    observations: dict[str, bool | float],
    checks: dict[str, bool],
    observation_threshold: float = 0.5,
) -> TruthGraphEvaluation:
    """Evaluate observable evidence against private, alternative truth paths.

    The return value contains IDs and aggregate coverage only.  Callers should
    not serialize ``graph`` itself into run events or public scorecards.
    """

    observed = {
        node_id
        for node_id, value in observations.items()
        if (
            (isinstance(value, bool) and value)
            or (
                not isinstance(value, bool)
                and float(value) >= observation_threshold
            )
        )
    }
    known_observed = observed & {node.id for node in graph.nodes}
    total_weight = sum(node.weight for node in graph.nodes)
    observed_weight = sum(
        node.weight for node in graph.nodes if node.id in known_observed
    )
    causal_coverage = observed_weight / total_weight if total_weight else 0.0

    path_results: list[ResolutionPathResult] = []
    for path in graph.acceptable_paths:
        missing_nodes = sorted(set(path.required_nodes) - known_observed)
        missing_groups = [
            alternatives
            for alternatives in path.any_of_nodes
            if not known_observed.intersection(alternatives)
        ]
        failed_checks = [
            check for check in path.required_checks if not checks.get(check, False)
        ]
        component_count = (
            len(path.required_nodes)
            + len(path.any_of_nodes)
            + len(path.required_checks)
        )
        passed_components = (
            len(path.required_nodes)
            - len(missing_nodes)
            + len(path.any_of_nodes)
            - len(missing_groups)
            + len(path.required_checks)
            - len(failed_checks)
        )
        coverage = passed_components / component_count if component_count else 1.0
        path_results.append(
            ResolutionPathResult(
                path_id=path.id,
                coverage=round(coverage, 6),
                satisfied=not (missing_nodes or missing_groups or failed_checks),
                missing_nodes=missing_nodes,
                missing_alternative_groups=missing_groups,
                failed_checks=failed_checks,
            )
        )

    best_path_coverage = max((result.coverage for result in path_results), default=0)
    satisfied_paths = [
        result.path_id for result in path_results if result.satisfied
    ]
    coverage_gate = min(
        1.0,
        causal_coverage / max(graph.minimum_causal_coverage, 0.000_001),
    )
    partial_credit = 100 * (0.7 * best_path_coverage + 0.3 * coverage_gate)
    return TruthGraphEvaluation(
        accepted=bool(satisfied_paths)
        and causal_coverage >= graph.minimum_causal_coverage,
        causal_coverage=round(causal_coverage, 6),
        best_path_coverage=round(best_path_coverage, 6),
        partial_credit=round(partial_credit, 3),
        satisfied_paths=satisfied_paths,
        observed_nodes=sorted(known_observed),
        paths=path_results,
    )
