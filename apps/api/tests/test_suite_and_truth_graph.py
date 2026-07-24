from pathlib import Path

import pytest

from app.challenge.spec import BudgetSpec
from app.scenario.suite import load_suite
from app.scenario.truth_graph import (
    ResolutionPath,
    TruthEdge,
    TruthGraph,
    TruthNode,
    evaluate_truth_graph,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_scenario_budget_contract_rejects_invalid_order_and_half_token_pair() -> None:
    with pytest.raises(ValueError, match="Provider-request"):
        BudgetSpec(
            soft_provider_requests=360,
            hard_provider_requests=360,
        )
    with pytest.raises(ValueError, match="configured together"):
        BudgetSpec(soft_total_tokens=10_000)


def sample_graph() -> TruthGraph:
    return TruthGraph(
        nodes=[
            TruthNode(id="cause.drift", kind="cause", label="contract drift", weight=3),
            TruthNode(id="condition.cache", kind="condition", label="stale cache"),
            TruthNode(id="remedy.patch", kind="remediation", label="minimal patch"),
            TruthNode(id="remedy.rollback", kind="remediation", label="safe rollback"),
        ],
        edges=[
            TruthEdge(
                source="condition.cache",
                target="cause.drift",
                relation="enables",
            ),
            TruthEdge(
                source="remedy.patch",
                target="cause.drift",
                relation="mitigates",
            ),
        ],
        acceptable_paths=[
            ResolutionPath(
                id="forward-fix",
                label="minimal forward fix",
                required_nodes=["cause.drift", "remedy.patch"],
                required_checks=["regression", "replay"],
            ),
            ResolutionPath(
                id="rollback",
                label="bounded rollback",
                required_nodes=["cause.drift", "remedy.rollback"],
                required_checks=["rollback_safe", "replay"],
            ),
        ],
        minimum_causal_coverage=0.5,
    )


def test_truth_graph_accepts_independent_resolution_paths() -> None:
    graph = sample_graph()
    forward = evaluate_truth_graph(
        graph,
        observations={"cause.drift": True, "remedy.patch": 0.91},
        checks={"regression": True, "replay": True},
    )
    rollback = evaluate_truth_graph(
        graph,
        observations={"cause.drift": True, "remedy.rollback": True},
        checks={"rollback_safe": True, "replay": True},
    )

    assert forward.accepted is True
    assert forward.satisfied_paths == ["forward-fix"]
    assert rollback.accepted is True
    assert rollback.satisfied_paths == ["rollback"]


def test_truth_graph_retains_partial_causal_credit_without_false_acceptance() -> None:
    result = evaluate_truth_graph(
        sample_graph(),
        observations={"cause.drift": True, "condition.cache": True},
        checks={"replay": True},
    )

    assert result.accepted is False
    assert 0 < result.partial_credit < 100
    assert result.best_path_coverage == 0.5
    assert result.paths[0].missing_nodes == ["remedy.patch"]
    assert result.paths[0].failed_checks == ["regression"]


def test_truth_graph_rejects_dangling_references() -> None:
    with pytest.raises(ValueError, match="unknown node"):
        TruthGraph(
            nodes=[TruthNode(id="cause.real", kind="cause", label="real")],
            edges=[
                TruthEdge(
                    source="cause.real",
                    target="symptom.missing",
                    relation="causes",
                )
            ],
            acceptable_paths=[
                ResolutionPath(
                    id="path",
                    label="path",
                    required_nodes=["cause.real"],
                )
            ],
        )


def test_suite_is_honest_about_current_leaderboard_readiness() -> None:
    suite = load_suite(
        PROJECT_ROOT / "suites" / "production-incidents" / "suite.yaml",
        PROJECT_ROOT / "scenarios",
    )

    assert suite.scenarios[0].version == "3.0.4"
    assert suite.readiness == {
        "active_families": 1,
        "held_out_families": 0,
        "scenario_references": 1,
        "required_active_families": 5,
        "required_held_out_families": 3,
        "required_scenarios": 20,
        "leaderboard_eligible": False,
    }


def test_suite_rejects_a_nonexistent_scenario(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        """
schema_version: 1
slug: test-suite
version: 1.0.0
name: Test
description: Test
families:
  - id: missing-family
    name: Missing
    description: Missing
scenarios:
  - slug: does-not-exist
    version: 1.0.0
    family: missing-family
    split: development
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing scenario"):
        load_suite(suite_path, PROJECT_ROOT / "scenarios")
