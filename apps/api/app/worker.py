import hashlib
import json
import logging
import tempfile
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import docker
from sqlalchemy import select

from app.config import get_settings
from app.crypto import SecretBox
from app.database import SessionLocal, create_schema
from app.events import append_event
from app.judging import (
    SemanticJudge,
    not_requested_review,
    safe_error,
    unavailable_review,
)
from app.models import (
    BenchmarkRun,
    ModelProfile,
    RunArtifact,
    RunEvent,
    RunnerHeartbeat,
    RunStatus,
    ServiceTelemetry,
    TaskDefinition,
)
from app.runner.engine import AgentEngine
from app.runner.faults import FaultController
from app.runner.protocol import ToolResult
from app.runner.providers import ModelClient
from app.runner.sandbox import DockerSandbox
from app.scenario import ScenarioRunResult, load_scenario
from app.seed import seed_canonical_task

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evil-runner")
settings = get_settings()


class Worker:
    def run_forever(self) -> None:
        create_schema()
        with SessionLocal() as session:
            seed_canonical_task(session)
        orphaned = self.reconcile_orphaned_runs()
        if orphaned:
            logger.warning(
                "Marked %d interrupted run(s) as orphaned after Runner startup",
                orphaned,
            )
        threading.Thread(
            target=self.heartbeat_forever,
            name="evil-runner-heartbeat",
            daemon=True,
        ).start()
        logger.info("Runner started; scenarios=%s", settings.scenarios_root)
        while True:
            run_id = self.claim()
            if run_id:
                self.execute(run_id)
            else:
                time.sleep(settings.runner_poll_seconds)

    @staticmethod
    def reconcile_orphaned_runs() -> int:
        interrupted_statuses = {
            RunStatus.preparing,
            RunStatus.running,
            RunStatus.scoring,
        }
        reconciled = 0
        with SessionLocal() as session:
            runs = session.scalars(
                select(BenchmarkRun)
                .where(BenchmarkRun.status.in_(interrupted_statuses))
                .order_by(BenchmarkRun.created_at)
            ).all()
            for run in runs:
                previous_status = run.status.value
                previous_stage = run.stage
                config = dict(run.config)
                config["pause_requested"] = False
                run.config = config
                run.status = RunStatus.failed
                run.stage = "Interrupted by Runner restart"
                run.error = (
                    "Runner restarted before this run completed. The in-memory "
                    "model conversation cannot be resumed safely."
                )
                run.completed_at = datetime.now(UTC)
                append_event(
                    session,
                    run.id,
                    "run.orphaned",
                    {
                        "reason": "runner_restart",
                        "resumable": False,
                        "previous_status": previous_status,
                        "previous_stage": previous_stage,
                    },
                )
                reconciled += 1
            session.commit()
        return reconciled

    def heartbeat_forever(self) -> None:
        while True:
            ready = False
            detail = "Docker daemon unavailable"
            metrics: dict[str, int | str | None] = {}
            client: docker.DockerClient | None = None
            try:
                client = docker.DockerClient(base_url=settings.docker_host)
                client.ping()
                info = client.info()
                version = client.version()
                metrics = {
                    "docker_version": version.get("Version"),
                    "storage_driver": info.get("Driver"),
                    "containers_running": int(info.get("ContainersRunning", 0)),
                    "containers_total": int(info.get("Containers", 0)),
                    "images": int(info.get("Images", 0)),
                    "cpu_count": int(info.get("NCPU", 0)),
                    "memory_total": int(info.get("MemTotal", 0)),
                }
                ready = True
                detail = "Rootless Docker daemon ready"
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"[:500]
            finally:
                if client:
                    client.close()
            try:
                with SessionLocal() as session:
                    heartbeat = session.get(RunnerHeartbeat, "default")
                    if heartbeat is None:
                        heartbeat = RunnerHeartbeat(name="default")
                        session.add(heartbeat)
                    heartbeat.docker_ready = ready
                    heartbeat.detail = detail
                    heartbeat.updated_at = datetime.now(UTC)
                    telemetry = session.get(ServiceTelemetry, "runner")
                    if telemetry is None:
                        telemetry = ServiceTelemetry(service="runner")
                        session.add(telemetry)
                    telemetry.healthy = ready
                    telemetry.metrics = metrics
                    telemetry.observed_at = datetime.now(UTC)
                    session.commit()
            except Exception:
                logger.exception("Could not persist Runner heartbeat")
            time.sleep(5)

    def claim(self) -> uuid.UUID | None:
        with SessionLocal() as session:
            statement = (
                select(BenchmarkRun)
                .where(BenchmarkRun.status == RunStatus.queued)
                .order_by(BenchmarkRun.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            run = session.scalar(statement)
            if not run:
                return None
            run.status = RunStatus.preparing
            run.stage = "Loading Scenario SDK"
            run.started_at = datetime.now(UTC)
            append_event(session, run.id, "run.preparing", {"stage": run.stage})
            session.commit()
            return run.id

    def execute(self, run_id: uuid.UUID) -> None:
        sandbox: DockerSandbox | None = None
        candidate_client: ModelClient | None = None
        started = time.monotonic()
        try:
            with SessionLocal() as session:
                run = session.get(BenchmarkRun, run_id)
                assert run is not None
                task = session.get(TaskDefinition, run.task_id)
                profile = session.get(ModelProfile, run.candidate_model_id)
                if not task or not profile:
                    raise RuntimeError("Run references missing task/model")
                if not profile.enabled:
                    raise RuntimeError("Candidate model profile is disabled")
                judge_model_id = run.judge_model_id
                judge_profile = (
                    session.get(ModelProfile, judge_model_id)
                    if judge_model_id
                    else None
                )
                if judge_profile is not None and not judge_profile.enabled:
                    judge_profile = None
                scenario_root = settings.scenarios_root / task.slug
                encrypted_key = profile.encrypted_api_key
                judge_encrypted_key = (
                    judge_profile.encrypted_api_key if judge_profile else None
                )
                run_config = dict(run.config)
                append_event(
                    session,
                    run_id,
                    "scenario.loaded",
                    {"root": str(scenario_root), "slug": task.slug, "version": task.version},
                )
                session.commit()

            scenario = load_scenario(scenario_root)
            if scenario.metadata.version != task.version:
                raise RuntimeError(
                    f"Scenario package version {scenario.metadata.version} does not match "
                    f"queued task version {task.version}"
                )
            with tempfile.TemporaryDirectory(prefix=f"evil-{run_id}-") as temporary:
                prepared = scenario.prepare(
                    Path(temporary),
                    scale=1.0,
                    instance_seed=run_config.get("instance_seed"),
                )
                prepared.metadata = prepared.metadata.model_copy(
                    update={
                        "budget": prepared.metadata.budget.model_copy(
                            update={
                                "soft_seconds": int(run_config["soft_seconds"]),
                                "hard_seconds": int(run_config["hard_seconds"]),
                                "soft_tool_calls": int(run_config["soft_tool_calls"]),
                                "hard_tool_calls": int(run_config["hard_tool_calls"]),
                            }
                        )
                    }
                )
                with SessionLocal() as session:
                    run = session.get(BenchmarkRun, run_id)
                    assert run is not None
                    run.status = RunStatus.preparing
                    run.stage = "Starting isolated sandbox"
                    append_event(
                        session,
                        run_id,
                        "scenario.prepared",
                        {
                            "workspace": "ephemeral",
                            "seed": prepared.metadata.seed,
                            "files": prepared.metadata.context_pressure.target_files,
                            "git_commits": prepared.metadata.context_pressure.target_git_commits,
                            "mirror_bytes": prepared.metadata.context_pressure.target_mirror_bytes,
                        },
                    )
                    session.commit()

                sandbox = DockerSandbox(settings, str(run_id))
                sandbox.start(prepared.workspace)
                self.set_stage(
                    run_id,
                    status=RunStatus.running,
                    stage="Candidate investigation",
                    kind="sandbox.started",
                )
                box = SecretBox(settings.app_secret)
                candidate_client = ModelClient(profile, box.decrypt(encrypted_key))
                faults = FaultController.load([Path(path) for path in prepared.private_state["fault_scripts"]])
                engine = AgentEngine(
                    run_id=run_id,
                    client=candidate_client,
                    sandbox=sandbox,
                    prepared=prepared,
                    faults=faults,
                )
                result = scenario.run(prepared, engine.run)
                self.set_stage(
                    run_id,
                    status=RunStatus.scoring,
                    stage="Collecting candidate artifacts",
                    kind="run.scoring",
                )
                truth = dict(prepared.private_state.get("truth", {}))
                dead_letter_baseline = str(truth["dead_letter_baseline"])
                palimpsest_baseline = str(truth["palimpsest_baseline"])
                result.artifacts.update(
                    {
                        "dead-letter.diff": sandbox.git_diff(
                            "dead-letter", dead_letter_baseline
                        ),
                        "dead-letter.status": sandbox.git_status("dead-letter"),
                        "palimpsest.diff": sandbox.git_diff(
                            "palimpsest", palimpsest_baseline
                        ),
                        "palimpsest.status": sandbox.git_status("palimpsest"),
                        "INVESTIGATION.md": (
                            sandbox.collect_text("INVESTIGATION.md")
                            or sandbox.collect_text("dead-letter/INVESTIGATION.md")
                        ),
                    }
                )
                static = self.hidden_check(
                    run_id,
                    "static",
                    lambda: sandbox.static_check(
                        dead_letter_baseline,
                        palimpsest_baseline,
                        list(
                            prepared.private_state["truth"].get(
                                "required_patch_paths",
                                [],
                            )
                        ),
                    ),
                )
                regression = self.hidden_check(
                    run_id,
                    "regression",
                    sandbox.hidden_regression,
                )
                mutation = self.hidden_check(
                    run_id,
                    "mutation",
                    sandbox.hidden_mutation,
                )
                runtime_contract = self.hidden_check(
                    run_id,
                    "runtime contract",
                    sandbox.hidden_runtime_contract,
                )
                golden = self.hidden_check(
                    run_id,
                    "golden replay",
                    lambda: sandbox.hidden_golden_replay(
                        Path(prepared.private_state["hidden_database_sql"])
                    ),
                )
                self.set_stage(
                    run_id,
                    stage="Resource and security audit",
                    kind="judge.audit.started",
                )
                stats = sandbox.stats()
                result.private_state.update(
                    {
                        "hidden_verification_passed": (
                            static.status == "ok"
                            and regression.status == "ok"
                            and mutation.status == "ok"
                            and runtime_contract.status == "ok"
                            and golden.status == "ok"
                        ),
                        "static_check": static.model_dump(mode="json"),
                        "regression": regression.model_dump(mode="json"),
                        "mutation": mutation.model_dump(mode="json"),
                        "runtime_contract": runtime_contract.model_dump(mode="json"),
                        "golden_replay": golden.model_dump(mode="json"),
                        "resource_check": stats,
                        "security_check": security_summary(result.events),
                    }
                )
                self.set_stage(
                    run_id,
                    stage="Resource and security audit",
                    kind="judge.audit.completed",
                )
                with SessionLocal() as session:
                    recorded_events = session.scalars(
                        select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.sequence)
                    ).all()
                    result.events = [
                        {"kind": event.kind, "sequence": event.sequence, **event.payload} for event in recorded_events
                    ]

                self.set_stage(
                    run_id,
                    stage="Scorecard aggregation",
                    kind="judge.scorecard.started",
                )
                scorecard = scenario.grade(prepared, result)
                semantic_review, semantic_artifacts = self.semantic_judge_review(
                    run_id=run_id,
                    judge_model_id=judge_model_id,
                    candidate_profile=profile,
                    judge_profile=judge_profile,
                    encrypted_key=judge_encrypted_key,
                    result=result,
                    scorecard=scorecard,
                )
                scorecard["semantic_review"] = semantic_review
                result.artifacts.update(
                    {
                        "scorecard.json": json.dumps(
                            scorecard,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        ),
                        "incident-audit.json": json.dumps(
                            result.private_state.get("incident_audit", {}),
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        ),
                        **semantic_artifacts,
                    }
                )
                self.set_stage(
                    run_id,
                    stage="Archiving run evidence",
                    kind="judge.scorecard.completed",
                    payload={"score": scorecard["score"], "maximum": scorecard["maximum"]},
                )
                result.events = self.run_events(run_id)
                archive_path = Path(settings.artifact_root) / f"{run_id}.tar.gz"
                scenario.archive(prepared, result, archive_path)
                archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
                self.complete(run_id, result, scorecard, archive_path, archive_sha)
        except Exception as exc:
            logger.error("Run %s failed: %s\n%s", run_id, exc, traceback.format_exc())
            self.fail(run_id, str(exc))
        finally:
            if candidate_client:
                candidate_client.close()
            if sandbox:
                sandbox.stop()
            logger.info("Run %s finished in %.2fs", run_id, time.monotonic() - started)

    def semantic_judge_review(
        self,
        *,
        run_id: uuid.UUID,
        judge_model_id: uuid.UUID | None,
        candidate_profile: ModelProfile,
        judge_profile: ModelProfile | None,
        encrypted_key: str | None,
        result: ScenarioRunResult,
        scorecard: dict[str, object],
    ) -> tuple[dict[str, object], dict[str, str]]:
        if judge_model_id is None:
            self.set_stage(
                run_id,
                stage="Scorecard aggregation",
                kind="judge.semantic.skipped",
                payload={"reason": "not_requested"},
            )
            return not_requested_review(), {}
        if judge_profile is None:
            review = unavailable_review(
                judge_model_id=str(judge_model_id),
                error="Selected judge model profile is unavailable.",
            )
            self.set_stage(
                run_id,
                stage="Semantic judge unavailable",
                kind="judge.semantic.failed",
                payload={
                    "judge_model_id": str(judge_model_id),
                    "error": review["errors"][0],
                },
            )
            return review, {
                "semantic-review.json": json.dumps(
                    review,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            }

        self.set_stage(
            run_id,
            stage="Semantic judge review",
            kind="judge.semantic.started",
            payload={
                "judge_model_id": str(judge_profile.id),
                "judge_name": judge_profile.name,
                "provider": judge_profile.provider.value,
                "model_id": judge_profile.model_id,
                "affects_primary_score": False,
            },
        )
        client: ModelClient | None = None
        try:
            box = SecretBox(settings.app_secret)
            client = ModelClient(
                judge_profile,
                box.decrypt(encrypted_key),
                timeout_seconds=settings.semantic_judge_timeout,
            )
            outcome = SemanticJudge(client).review(
                result,
                scorecard,
                candidate_identity_tokens=[
                    candidate_profile.name,
                    candidate_profile.model_id,
                ],
            )
            review = outcome.review
            artifacts = {
                "semantic-review.json": json.dumps(
                    review,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                "semantic-judge-input.json": json.dumps(
                    outcome.packet,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                "semantic-judge-raw.json": json.dumps(
                    outcome.raw_outputs,
                    ensure_ascii=False,
                    indent=2,
                ),
            }
        except Exception as exc:
            review = unavailable_review(
                judge_model_id=str(judge_model_id),
                error=safe_error(exc),
            )
            review["judge"] = {
                "profile_id": str(judge_profile.id),
                "name": judge_profile.name,
                "provider": judge_profile.provider.value,
                "model_id": judge_profile.model_id,
            }
            artifacts = {
                "semantic-review.json": json.dumps(
                    review,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            }
        finally:
            if client:
                client.close()

        event_kind = (
            "judge.semantic.completed"
            if review["status"] == "completed"
            else "judge.semantic.failed"
        )
        self.set_stage(
            run_id,
            stage=(
                "Semantic judge completed"
                if review["status"] == "completed"
                else "Semantic judge failed; deterministic score preserved"
            ),
            kind=event_kind,
            payload={
                "judge_model_id": str(judge_model_id),
                "status": review["status"],
                "semantic_score": review.get("score"),
                "maximum": review.get("maximum", 100),
                "reliability": dict(review.get("reliability") or {}).get("level"),
                "attempts": review.get("attempts", 0),
                "usage": review.get("usage", {}),
                "affects_primary_score": False,
            },
        )
        return review, artifacts

    @staticmethod
    def run_events(run_id: uuid.UUID) -> list[dict[str, object]]:
        with SessionLocal() as session:
            recorded_events = session.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id)
                .order_by(RunEvent.sequence)
            ).all()
            return [
                {
                    "kind": event.kind,
                    "sequence": event.sequence,
                    **event.payload,
                }
                for event in recorded_events
            ]

    def set_stage(
        self,
        run_id: uuid.UUID,
        *,
        stage: str,
        kind: str,
        status: RunStatus | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        with SessionLocal() as session:
            run = session.get(BenchmarkRun, run_id)
            assert run is not None
            if status is not None:
                run.status = status
            run.stage = stage
            append_event(session, run_id, kind, {"stage": stage, **(payload or {})})
            session.commit()

    def hidden_check(
        self,
        run_id: uuid.UUID,
        name: str,
        operation: Callable[[], ToolResult],
    ) -> ToolResult:
        stage = f"Hidden judge · {name}"
        self.set_stage(
            run_id,
            stage=stage,
            kind="judge.check.started",
            payload={"check": name},
        )
        started = time.monotonic()
        try:
            result = operation()
        except Exception as exc:
            self.set_stage(
                run_id,
                stage=stage,
                kind="judge.check.failed",
                payload={
                    "check": name,
                    "duration_ms": round((time.monotonic() - started) * 1_000),
                    "error_type": type(exc).__name__,
                },
            )
            raise
        self.set_stage(
            run_id,
            stage=stage,
            kind="judge.check.completed",
            payload={
                "check": name,
                "status": getattr(result, "status", "ok"),
                "duration_ms": round((time.monotonic() - started) * 1_000),
            },
        )
        return result

    def complete(
        self,
        run_id: uuid.UUID,
        result: ScenarioRunResult,
        scorecard: dict,
        archive_path: Path,
        archive_sha: str,
    ) -> None:
        with SessionLocal() as session:
            run = session.get(BenchmarkRun, run_id)
            assert run is not None
            run.status = RunStatus.completed
            run.stage = "Completed"
            run.score = float(scorecard["score"])
            run.scorecard = scorecard
            run.tool_calls = result.tool_calls
            run.input_tokens = int(result.private_state.get("input_tokens", 0))
            run.output_tokens = int(result.private_state.get("output_tokens", 0))
            run.completed_at = datetime.now(UTC)
            session.add(
                RunArtifact(
                    run_id=run_id,
                    name=archive_path.name,
                    media_type="application/gzip",
                    path=str(archive_path),
                    sha256=archive_sha,
                    size=archive_path.stat().st_size,
                    metadata_json={"kind": "scenario-run-archive"},
                )
            )
            append_event(
                session,
                run_id,
                "run.completed",
                {"score": run.score, "maximum": scorecard["maximum"]},
            )
            session.commit()

    def fail(self, run_id: uuid.UUID, message: str) -> None:
        with SessionLocal() as session:
            run = session.get(BenchmarkRun, run_id)
            if not run:
                return
            run.status = RunStatus.failed
            run.stage = "Failed"
            run.error = message[:4_000]
            run.completed_at = datetime.now(UTC)
            append_event(session, run_id, "run.failed", {"error": message[:1_000]})
            session.commit()


def security_summary(events: list[dict]) -> dict:
    calls = [event for event in events if event.get("kind") == "tool.call"]
    results = [event for event in events if event.get("kind") == "tool.result"]
    policy_violations = [event for event in results if event.get("policy_violation")]
    return {
        "tool_calls": len(calls),
        "policy_violations": len(policy_violations),
        "violation_types": sorted(
            {
                str(event.get("policy_violation"))
                for event in policy_violations
            }
        ),
        "passed": not policy_violations,
    }


def main() -> None:
    Worker().run_forever()


if __name__ == "__main__":
    main()
