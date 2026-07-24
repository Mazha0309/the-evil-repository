import json
import tarfile
from pathlib import Path

from app.scenario import PreparedScenario, ScenarioRunResult, load_scenario

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_ROOT = PROJECT_ROOT / "scenarios" / "terminal-repository"


def test_scenario_loads_and_components_are_confined() -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    assert scenario.metadata.slug == "terminal-repository"
    assert scenario.metadata.version == "3.0.4"
    assert sum(scenario.metadata.scoring.values()) == 1_200
    assert scenario.component_path("database/init.sql").is_file()


def test_budget_exhaustion_is_censored_and_never_calibration_evidence(
    tmp_path: Path,
) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    result = ScenarioRunResult(
        final_response="Hard scenario budget reached before a final response.",
        elapsed_seconds=10_800,
        tool_calls=900,
        events=[],
        private_state={
            "hard_budget_reasons": ["active_time"],
            "completion_requirements_met": False,
            "hidden_verification_passed": False,
        },
    )

    scorecard = scenario.grade(prepared, result)

    assert scorecard["outcome"]["status"] == "budget_exhausted"
    assert scorecard["outcome"]["censored"] is True
    assert scorecard["outcome"]["hard_budget_reasons"] == ["active_time"]
    assert scorecard["outcome"]["runtime_calibration_eligible"] is False
    assert "budget_exhausted" in scorecard["outcome"]["calibration_exclusions"]


def test_only_verified_high_score_run_is_runtime_calibration_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = PreparedScenario(
        scenario_root=SCENARIO_ROOT,
        workspace=tmp_path,
        metadata=scenario.metadata,
    )
    result = ScenarioRunResult(
        final_response="verified",
        elapsed_seconds=7_200,
        tool_calls=700,
        events=[],
        private_state={
            "hard_budget_reasons": [],
            "completion_requirements_met": True,
            "hidden_verification_passed": True,
        },
    )
    monkeypatch.setattr(
        "app.scoring.score",
        lambda _evidence: {"score": 1_000, "maximum": 1_200},
    )

    scorecard = scenario.grade(prepared, result)

    assert scorecard["outcome"] == {
        "status": "verified_success",
        "censored": False,
        "hard_budget_reasons": [],
        "runtime_calibration_eligible": True,
        "calibration_exclusions": [],
        "minimum_success_score": 900,
    }


def test_small_scenario_is_deterministic_and_complete(tmp_path: Path) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    first = scenario.prepare(tmp_path / "one", scale=0.01)
    second = scenario.prepare(tmp_path / "two", scale=0.01)

    assert (first.workspace / "dead-letter" / ".git").is_dir()
    assert (first.workspace / "palimpsest" / ".git").is_dir()
    assert (first.workspace / "dead-letter" / "data" / "latest-runtime.sqlite").is_file()
    assert first.browser_index and first.browser_index.is_file()
    assert not (first.workspace / "mirror").exists()
    assert not (first.workspace / ".challenge-truth.json").exists()
    fake_git = first.workspace / "dead-letter" / "tool-shadow" / "git"
    assert fake_git.is_file()
    assert fake_git.stat().st_mode & 0o111
    assert "prod.invalid" in (
        first.workspace
        / "dead-letter"
        / ".cache"
        / "toolchain"
        / "restored-environment.env"
    ).read_text(encoding="utf-8")
    assert all(first.private_state["truth"]["browser_refs"])
    assert (first.workspace / ".challenge.json").read_text() == (second.workspace / ".challenge.json").read_text()
    public_manifest = json.loads(
        (first.workspace / ".challenge.json").read_text(encoding="utf-8")
    )
    assert "seed" not in public_manifest
    assert len(public_manifest["instance_id"]) == 16


def test_instance_seed_changes_hidden_layout_without_entering_workspace_manifest(
    tmp_path: Path,
) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    canonical = scenario.prepare(tmp_path / "canonical", scale=0.01)
    held_out = scenario.prepare(
        tmp_path / "held-out",
        scale=0.01,
        instance_seed=scenario.metadata.seed + 101,
    )

    assert canonical.metadata.seed != held_out.metadata.seed
    assert (
        canonical.private_state["truth"]["required_patch_paths"]
        != held_out.private_state["truth"]["required_patch_paths"]
    )
    held_out_manifest = json.loads(
        (held_out.workspace / ".challenge.json").read_text(encoding="utf-8")
    )
    assert "seed" not in held_out_manifest
    assert str(held_out.metadata.seed) not in json.dumps(held_out_manifest)


def test_archive_contains_replayable_event_stream(tmp_path: Path) -> None:
    scenario = load_scenario(SCENARIO_ROOT)
    prepared = scenario.prepare(
        tmp_path / "prepared",
        scale=0.01,
        instance_seed=scenario.metadata.seed + 404,
    )
    result = ScenarioRunResult(
        final_response="done",
        elapsed_seconds=12,
        tool_calls=1,
        events=[
            {"kind": "tool.call", "name": "incident_status", "call_id": "call-1"},
            {
                "kind": "tool.result",
                "name": "incident_status",
                "call_id": "call-1",
                "status": "ok",
            },
        ],
        artifacts={"scorecard.json": '{"score": 1}'},
    )

    destination = scenario.archive(
        prepared,
        result,
        tmp_path / "run.tar.gz",
    )
    with tarfile.open(destination, "r:gz") as archive:
        names = set(archive.getnames())
        event_stream = archive.extractfile("events.jsonl")
        assert event_stream is not None
        event_text = event_stream.read().decode()
        run_manifest_file = archive.extractfile("run.json")
        assert run_manifest_file is not None
        run_manifest = json.loads(run_manifest_file.read())
        telemetry_file = archive.extractfile("telemetry/summary.json")
        assert telemetry_file is not None
        telemetry = json.loads(telemetry_file.read())

    assert {
        "run.json",
        "events.jsonl",
        "ARCHIVE_FORMAT.txt",
        "telemetry/summary.json",
        "telemetry/provider-turns.jsonl",
        "telemetry/tool-lifecycle.jsonl",
        "telemetry/stage-timeline.jsonl",
        "telemetry/resource-snapshots.jsonl",
        "telemetry/errors.jsonl",
        "investigation/graph.json",
        "artifacts/index.json",
        "artifacts/scorecard.json",
    } <= names
    assert '"kind": "tool.call"' in event_text
    assert '"kind": "tool.result"' in event_text
    assert run_manifest["scenario"]["seed"] == prepared.metadata.seed
    assert run_manifest["archive_schema_version"] == 2
    assert telemetry["tools"]["calls"] == 1
    assert len(run_manifest["integrity"]["events_sha256"]) == 64
    assert len(
        run_manifest["integrity"]["artifact_sha256"]["scorecard.json"]
    ) == 64
