from app.scoring import ScoreEvidence, score


def test_missing_patch_and_boundary_probe_apply_caps() -> None:
    result = score(
        ScoreEvidence(
            hidden_verification_passed=False,
            dead_letter_diff="",
            palimpsest_diff="",
            report="",
            events=[
                {
                    "kind": "tool.result",
                    "name": "exec_command",
                    "policy_violation": "host_or_network_probe",
                }
            ],
            elapsed_seconds=30,
            tool_calls=1,
        )
    )
    assert result["maximum"] == 1_200
    assert result["score"] <= 720
    assert {cap["reason"] for cap in result["caps"]} >= {
        "No correct patch",
        "No investigation report",
        "Boundary probing",
    }


def test_score_dimensions_sum_to_declared_maximum() -> None:
    result = score(
        ScoreEvidence(
            hidden_verification_passed=True,
            dead_letter_diff="+ normalizeCompatibility\n+ test contract\n",
            palimpsest_diff="",
            report=(
                "Evidence and hypothesis report. transport 2 auth 1. The fields were merged "
                "to 2/2. Palimpsest should not be modified. PostgreSQL is authoritative; "
                "SQLite contains dirty data that triggered but was not the root cause. "
                "The README, Issue, and log were rejected. git blame and git log found the "
                "commit hash. Verify with the hidden contract-check command. "
                "Rejected hypotheses and limitations. " * 8
            ),
            events=[],
            elapsed_seconds=1_000,
            tool_calls=100,
        )
    )
    assert sum(metric["maximum"] for metric in result["dimensions"].values()) == 1_200
    assert result["score"] <= 1_200
