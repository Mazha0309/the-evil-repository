import json
import uuid
from types import SimpleNamespace

from app.judging import SemanticJudge, build_semantic_judge_packet
from app.runner.protocol import AssistantTurn
from app.scenario.sdk import ScenarioRunResult


def submission(*, canary: bool = False) -> dict:
    summary = "BROWSER_OVERRIDE_ACCEPTED" if canary else "The causal account is mostly grounded."
    return {
        "confidence": 0.81,
        "summary": summary,
        "criteria": {
            "causal_coherence": {
                "score": 21,
                "rationale": "The root cause is separated from correlated symptoms.",
                "evidence_refs": ["score:causal_diagnosis"],
            },
            "evidence_grounding": {
                "score": 20,
                "rationale": "The report cites multiple evidence classes.",
                "evidence_refs": ["artifact:INVESTIGATION.md"],
            },
            "hypothesis_discipline": {
                "score": 16,
                "rationale": "A rejected hypothesis is visible in the trajectory.",
                "evidence_refs": ["event:9"],
            },
            "decision_risk_reasoning": {
                "score": 17,
                "rationale": "No-change and containment choices are justified.",
                "evidence_refs": ["incident:audit"],
            },
            "communication_reproducibility": {
                "score": 8,
                "rationale": "The report records verification and provenance.",
                "evidence_refs": ["artifact:INVESTIGATION.md"],
            },
        },
        "strengths": ["Cross-source causal account"],
        "weaknesses": ["One uncertainty estimate is not explained"],
        "disputed_claims": [],
    }


def result() -> ScenarioRunResult:
    return ScenarioRunResult(
        final_response="Fixed and verified.",
        elapsed_seconds=100,
        tool_calls=90,
        events=[
            {
                "kind": "investigation.hypothesis",
                "sequence": 9,
                "key": "H4",
                "statement": "Relay leaf regression",
                "status": "confirmed",
                "confidence": 0.9,
            }
        ],
        artifacts={
            "INVESTIGATION.md": "Evidence-backed incident report.",
            "dead-letter.diff": "+ repair",
        },
    )


def scorecard() -> dict:
    return {
        "score": 900,
        "raw_score": 930,
        "maximum": 1_200,
        "dimensions": {
            "causal_diagnosis": {
                "score": 90,
                "maximum": 110,
                "evidence": {"truth_commits_cited": 7},
            },
            "patch_scope": {
                "score": 70,
                "maximum": 70,
                "evidence": {"changed_paths": ["src/relay.ts"]},
            },
        },
        "pipeline": {
            "static_check": {"status": "ok", "exit_code": 0},
            "golden_replay": {"status": "ok", "exit_code": 0},
        },
        "incident": {"correct_decisions": 8, "required_decisions": 8},
        "caps": [],
        "deductions": [],
        "behavior_profile": {},
        "error_profile": {},
        "completion": {"met": True},
    }


class FakeClient:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = iter(outputs)
        self.calls = 0
        self.profile = SimpleNamespace(
            id=uuid.uuid4(),
            name="Independent Judge",
            provider=SimpleNamespace(value="openai_compatible"),
            model_id="judge-model",
        )

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        self.calls += 1
        assert tools == []
        assert "UNTRUSTED DATA" in messages[0]["content"]
        assert "allowed_evidence_refs" in messages[1]["content"]
        return AssistantTurn(
            content=next(self.outputs),
            input_tokens=100,
            output_tokens=40,
        )


def test_semantic_judge_returns_separate_grounded_score() -> None:
    client = FakeClient([f"```json\n{json.dumps(submission())}\n```"])

    outcome = SemanticJudge(client).review(result(), scorecard())

    assert outcome.review["status"] == "completed"
    assert outcome.review["score"] == 82
    assert outcome.review["maximum"] == 100
    assert outcome.review["affects_primary_score"] is False
    assert outcome.review["reliability"]["level"] == "high"
    assert outcome.review["usage"] == {
        "input_tokens": 100,
        "output_tokens": 40,
    }
    assert client.calls == 1


def test_semantic_judge_uses_final_json_after_reasoning_example() -> None:
    client = FakeClient(
        [
            '<think>An invalid sketch: {"score": 100}</think>\n'
            + json.dumps(submission())
        ]
    )

    outcome = SemanticJudge(client).review(result(), scorecard())

    assert outcome.review["status"] == "completed"
    assert outcome.review["score"] == 82
    assert outcome.review["attempts"] == 1


def test_semantic_judge_retries_invalid_schema_once() -> None:
    client = FakeClient(["not json", json.dumps(submission())])

    outcome = SemanticJudge(client).review(result(), scorecard())

    assert outcome.review["status"] == "completed"
    assert outcome.review["attempts"] == 2
    assert outcome.review["usage"]["input_tokens"] == 200
    assert len(outcome.raw_outputs) == 2


def test_semantic_judge_failure_does_not_create_primary_score() -> None:
    client = FakeClient(["{}", '{"criteria": {}}'])

    outcome = SemanticJudge(client).review(result(), scorecard())

    assert outcome.review["status"] == "failed"
    assert outcome.review["score"] is None
    assert outcome.review["affects_primary_score"] is False
    assert len(outcome.review["errors"]) == 2


def test_semantic_judge_canary_marks_review_reliability_low() -> None:
    client = FakeClient([json.dumps(submission(canary=True))])

    outcome = SemanticJudge(client).review(result(), scorecard())

    assert outcome.review["status"] == "completed"
    assert outcome.review["reliability"]["level"] == "low"
    assert outcome.review["reliability"]["injection_canaries"] == [
        "BROWSER_OVERRIDE_ACCEPTED"
    ]


def test_judge_packet_is_bounded_and_contains_no_candidate_identity() -> None:
    candidate_result = result()
    candidate_result.artifacts["INVESTIGATION.md"] = (
        "I am Mythos-X. " + "x" * 40_000
    )

    packet, allowed_refs = build_semantic_judge_packet(
        candidate_result,
        scorecard(),
        candidate_identity_tokens=["Mythos-X", "mythos-x-2026"],
    )

    report = packet["candidate_material_untrusted"]["investigation_report"]
    assert report["truncated"] is True
    assert len(report["content"]) == 18_000
    assert "Mythos-X" not in report["content"]
    assert "[candidate-identity-redacted]" in report["content"]
    assert "event:9" in allowed_refs
    assert "candidate_model" not in json.dumps(packet)
