import hashlib
import json
import logging
import tempfile
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
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
    PlatformSettings,
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
from app.scenario import PreparedScenario, Scenario, ScenarioRunResult, load_scenario
from app.scenario.agent_graph import derive_agent_graph
from app.seed import seed_canonical_task

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evil-runner")
settings = get_settings()


class Worker:
    def __init__(self) -> None:
        self._active_run_ids: set[uuid.UUID] = set()
        self._active_lock = threading.Lock()

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
        initial_concurrency = self.concurrency_limit()
        logger.info(
            "Runner started; scenarios=%s concurrency=%d",
            settings.scenarios_root,
            initial_concurrency,
        )
        futures: dict[Future[None], uuid.UUID] = {}
        with ThreadPoolExecutor(
            max_workers=16,
            thread_name_prefix="evil-run",
        ) as executor:
            while True:
                self.reap_finished(futures)
                claimed = self.fill_available_slots(executor, futures)
                if claimed == 0:
                    time.sleep(settings.runner_poll_seconds)

    def fill_available_slots(
        self,
        executor: ThreadPoolExecutor,
        futures: dict[Future[None], uuid.UUID],
    ) -> int:
        claimed = 0
        concurrency = self.concurrency_limit()
        while len(futures) < concurrency:
            run_id = self.claim()
            if run_id is None:
                break
            future = executor.submit(self.execute_tracked, run_id)
            futures[future] = run_id
            claimed += 1
        return claimed

    @staticmethod
    def concurrency_limit() -> int:
        with SessionLocal() as session:
            platform = session.get(PlatformSettings, "default")
            if platform is None:
                return settings.runner_concurrency
            return max(1, min(16, int(platform.runner_concurrency)))

    @staticmethod
    def reap_finished(futures: dict[Future[None], uuid.UUID]) -> None:
        for future, run_id in list(futures.items()):
            if not future.done():
                continue
            futures.pop(future)
            try:
                future.result()
            except Exception:
                logger.exception("Run worker thread crashed unexpectedly: %s", run_id)

    def execute_tracked(self, run_id: uuid.UUID) -> None:
        with self._active_lock:
            self._active_run_ids.add(run_id)
        try:
            self.execute(run_id)
        finally:
            with self._active_lock:
                self._active_run_ids.discard(run_id)

    def active_run_count(self) -> int:
        with self._active_lock:
            return len(self._active_run_ids)

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
                .where(
                    BenchmarkRun.status.in_(interrupted_statuses),
                    BenchmarkRun.archived_at.is_(None),
                )
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
                concurrency = self.concurrency_limit()
                workers_active = self.active_run_count()
                metrics = {
                    "docker_version": version.get("Version"),
                    "storage_driver": info.get("Driver"),
                    "containers_running": int(info.get("ContainersRunning", 0)),
                    "containers_total": int(info.get("Containers", 0)),
                    "images": int(info.get("Images", 0)),
                    "cpu_count": int(info.get("NCPU", 0)),
                    "memory_total": int(info.get("MemTotal", 0)),
                    "worker_concurrency": concurrency,
                    "workers_active": workers_active,
                    "workers_available": max(
                        0,
                        concurrency - workers_active,
                    ),
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
                .where(
                    BenchmarkRun.status == RunStatus.queued,
                    BenchmarkRun.archived_at.is_(None),
                )
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
        scenario: Scenario | None = None
        prepared: PreparedScenario | None = None
        engine: AgentEngine | None = None
        result: ScenarioRunResult | None = None
        started = time.monotonic()
        try:
            with SessionLocal() as session:
                run = session.get(BenchmarkRun, run_id)
                assert run is not None
                if run.status == RunStatus.cancelled:
                    return
                task = session.get(TaskDefinition, run.task_id)
                profile = session.get(ModelProfile, run.candidate_model_id)
                if not task or not profile:
                    raise RuntimeError("Run references missing task/model")
                if not profile.enabled or profile.archived_at is not None:
                    raise RuntimeError("Candidate model profile is unavailable")
                judge_model_id = run.judge_model_id
                judge_profile = session.get(ModelProfile, judge_model_id) if judge_model_id else None
                if judge_profile is not None and (
                    not judge_profile.enabled or judge_profile.archived_at is not None
                ):
                    judge_profile = None
                scenario_root = settings.scenarios_root / task.slug
                encrypted_key = profile.encrypted_api_key
                judge_encrypted_key = judge_profile.encrypted_api_key if judge_profile else None
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
                                "soft_provider_requests": int(
                                    run_config.get(
                                        "soft_provider_requests",
                                        prepared.metadata.budget.soft_provider_requests,
                                    )
                                ),
                                "hard_provider_requests": int(
                                    run_config.get(
                                        "hard_provider_requests",
                                        prepared.metadata.budget.hard_provider_requests,
                                    )
                                ),
                                "soft_total_tokens": run_config.get(
                                    "soft_total_tokens"
                                ),
                                "hard_total_tokens": run_config.get(
                                    "hard_total_tokens"
                                ),
                            }
                        )
                    }
                )
                if self.is_cancelled(run_id):
                    return
                with SessionLocal() as session:
                    run = session.scalar(select(BenchmarkRun).where(BenchmarkRun.id == run_id).with_for_update())
                    assert run is not None
                    if run.status == RunStatus.cancelled:
                        return
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
                candidate_client = ModelClient(
                    profile,
                    box.decrypt(encrypted_key),
                    on_retry=lambda payload: self.record_provider_retry(
                        run_id,
                        "candidate",
                        payload,
                    ),
                )
                faults = FaultController.load([Path(path) for path in prepared.private_state["fault_scripts"]])
                engine = AgentEngine(
                    run_id=run_id,
                    client=candidate_client,
                    sandbox=sandbox,
                    prepared=prepared,
                    faults=faults,
                )
                result = scenario.run(prepared, engine.run)
                if self.is_cancelled(run_id):
                    return
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
                        "dead-letter.diff": sandbox.git_diff("dead-letter", dead_letter_baseline),
                        "dead-letter.status": sandbox.git_status("dead-letter"),
                        "palimpsest.diff": sandbox.git_diff("palimpsest", palimpsest_baseline),
                        "palimpsest.status": sandbox.git_status("palimpsest"),
                        "INVESTIGATION.md": (
                            sandbox.collect_text("INVESTIGATION.md")
                            or sandbox.collect_text("dead-letter/INVESTIGATION.md")
                        ),
                    }
                )
                if self.is_cancelled(run_id):
                    return
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
                if self.is_cancelled(run_id):
                    return
                regression = self.hidden_check(
                    run_id,
                    "regression",
                    sandbox.hidden_regression,
                )
                if self.is_cancelled(run_id):
                    return
                mutation = self.hidden_check(
                    run_id,
                    "mutation",
                    sandbox.hidden_mutation,
                )
                if self.is_cancelled(run_id):
                    return
                runtime_contract = self.hidden_check(
                    run_id,
                    "runtime contract",
                    sandbox.hidden_runtime_contract,
                )
                if self.is_cancelled(run_id):
                    return
                golden = self.hidden_check(
                    run_id,
                    "golden replay",
                    lambda: sandbox.hidden_golden_replay(Path(prepared.private_state["hidden_database_sql"])),
                )
                if self.is_cancelled(run_id):
                    return
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
                scorecard["resources"] = dict(
                    result.private_state.get("resource_ledger", {})
                )
                agent_graph = derive_agent_graph(result.events).model_dump(
                    mode="json"
                )
                scorecard["agent_graph"] = {
                    "schema_version": agent_graph["schema_version"],
                    "execution_mode": agent_graph["execution_mode"],
                    "agent_count": len(agent_graph["nodes"]),
                    "edge_count": len(agent_graph["edges"]),
                }
                if self.is_cancelled(run_id):
                    return
                semantic_review, semantic_artifacts = self.semantic_judge_review(
                    run_id=run_id,
                    judge_model_id=judge_model_id,
                    candidate_profile=profile,
                    judge_profile=judge_profile,
                    encrypted_key=judge_encrypted_key,
                    result=result,
                    scorecard=scorecard,
                )
                if self.is_cancelled(run_id):
                    return
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
                        "resource-ledger.json": json.dumps(
                            result.private_state.get("resource_ledger", {}),
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        ),
                        "agent-graph.json": json.dumps(
                            agent_graph,
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
                if self.is_cancelled(run_id):
                    return
                archive_path = Path(settings.artifact_root) / f"{run_id}.tar.gz"
                scenario.archive(prepared, result, archive_path)
                archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
                self.complete(run_id, result, scorecard, archive_path, archive_sha)
        except Exception as exc:
            logger.error("Run %s failed: %s\n%s", run_id, exc, traceback.format_exc())
            checkpoint = None
            try:
                checkpoint = self.create_failure_checkpoint(
                    run_id=run_id,
                    scenario=scenario,
                    prepared=prepared,
                    engine=engine,
                    result=result,
                    sandbox=sandbox,
                    error=exc,
                )
            except Exception:
                logger.exception("Could not preserve failure checkpoint for run %s", run_id)
            self.fail(run_id, str(exc), checkpoint=checkpoint)
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
                on_retry=lambda payload: self.record_provider_retry(
                    run_id,
                    "semantic_judge",
                    payload,
                ),
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

        event_kind = "judge.semantic.completed" if review["status"] == "completed" else "judge.semantic.failed"
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
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.sequence)
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
            run = session.scalar(select(BenchmarkRun).where(BenchmarkRun.id == run_id).with_for_update())
            assert run is not None
            if run.status == RunStatus.cancelled:
                return
            if status is not None:
                run.status = status
            run.stage = stage
            append_event(session, run_id, kind, {"stage": stage, **(payload or {})})
            session.commit()

    @staticmethod
    def record_provider_retry(
        run_id: uuid.UUID,
        phase: str,
        payload: dict[str, object],
    ) -> None:
        with SessionLocal() as session:
            run = session.get(BenchmarkRun, run_id)
            if not run or run.status == RunStatus.cancelled:
                return
            append_event(
                session,
                run_id,
                "provider.retry",
                {
                    **(
                        {
                            "agent_id": "candidate/root",
                            "agent_role": "primary",
                        }
                        if phase == "candidate"
                        else {}
                    ),
                    "phase": phase,
                    **payload,
                },
            )
            session.commit()

    @staticmethod
    def is_cancelled(run_id: uuid.UUID) -> bool:
        with SessionLocal() as session:
            run = session.get(BenchmarkRun, run_id)
            return bool(run and run.status == RunStatus.cancelled)

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
            run = session.scalar(select(BenchmarkRun).where(BenchmarkRun.id == run_id).with_for_update())
            assert run is not None
            if run.status == RunStatus.cancelled:
                return
            run.status = RunStatus.completed
            outcome = dict(scorecard.get("outcome", {}))
            budget_exhausted = bool(outcome.get("censored", False))
            run.stage = "Budget exhausted" if budget_exhausted else "Completed"
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
            if budget_exhausted:
                append_event(
                    session,
                    run_id,
                    "run.budget_exhausted",
                    {
                        "reasons": outcome.get("hard_budget_reasons", []),
                        "score": run.score,
                        "maximum": scorecard["maximum"],
                        "censored": True,
                    },
                )
            append_event(
                session,
                run_id,
                "run.completed",
                {
                    "score": run.score,
                    "maximum": scorecard["maximum"],
                    "outcome": outcome.get("status", "evaluated"),
                    "censored": budget_exhausted,
                },
            )
            session.commit()

    def create_failure_checkpoint(
        self,
        *,
        run_id: uuid.UUID,
        scenario: Scenario | None,
        prepared: PreparedScenario | None,
        engine: AgentEngine | None,
        result: ScenarioRunResult | None,
        sandbox: DockerSandbox | None,
        error: Exception,
    ) -> tuple[Path, str] | None:
        if scenario is None or prepared is None or self.is_cancelled(run_id):
            return None
        checkpoint_result = result
        if checkpoint_result is None:
            checkpoint_result = (
                engine.checkpoint_result(error)
                if engine is not None
                else ScenarioRunResult(
                    final_response=(
                        f"Run interrupted by {type(error).__name__} before the "
                        "candidate engine started."
                    ),
                    elapsed_seconds=0,
                    tool_calls=0,
                    events=[],
                    private_state={
                        "failure": {
                            "type": type(error).__name__,
                            "message": str(error)[:4_000],
                        }
                    },
                )
            )
        checkpoint_result.private_state["failure"] = {
            "type": type(error).__name__,
            "message": str(error)[:4_000],
        }
        collection_errors: dict[str, str] = {}

        def collect(name: str, operation: Callable[[], str]) -> None:
            try:
                checkpoint_result.artifacts[name] = operation()
            except Exception as collection_error:
                collection_errors[name] = (
                    f"{type(collection_error).__name__}: {collection_error}"
                )[:1_000]

        if sandbox is not None and sandbox.container is not None:
            truth = dict(prepared.private_state.get("truth", {}))
            repositories = (
                ("dead-letter", str(truth.get("dead_letter_baseline", "HEAD"))),
                ("palimpsest", str(truth.get("palimpsest_baseline", "HEAD"))),
            )
            for repository, baseline in repositories:
                collect(
                    f"{repository}.diff",
                    lambda repository=repository, baseline=baseline: sandbox.git_diff(
                        repository,
                        baseline,
                    ),
                )
                collect(
                    f"{repository}.status",
                    lambda repository=repository: sandbox.git_status(repository),
                )
            collect(
                "INVESTIGATION.md",
                lambda: (
                    sandbox.collect_text("INVESTIGATION.md")
                    or sandbox.collect_text("dead-letter/INVESTIGATION.md")
                ),
            )
        checkpoint_result.events = self.run_events(run_id)
        failure_summary = {
            "kind": "unexpected-run-failure",
            "error_type": type(error).__name__,
            "error": str(error)[:4_000],
            "created_at": datetime.now(UTC).isoformat(),
            "resumable": False,
            "replayable": True,
            "candidate_workspace_preserved_as": "repository diffs and bounded artifacts",
            "collection_errors": collection_errors,
            "resource_ledger": checkpoint_result.private_state.get(
                "resource_ledger",
                {},
            ),
        }
        checkpoint_result.artifacts.update(
            {
                "failure-summary.json": json.dumps(
                    failure_summary,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                "resource-ledger.json": json.dumps(
                    checkpoint_result.private_state.get("resource_ledger", {}),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                "incident-audit.json": json.dumps(
                    checkpoint_result.private_state.get("incident_audit", {}),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
            }
        )
        archive_path = (
            Path(settings.artifact_root)
            / f"{run_id}-failure-checkpoint.tar.gz"
        )
        scenario.archive(prepared, checkpoint_result, archive_path)
        archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        logger.info(
            "Preserved failure checkpoint for run %s at %s",
            run_id,
            archive_path,
        )
        return archive_path, archive_sha

    def fail(
        self,
        run_id: uuid.UUID,
        message: str,
        *,
        checkpoint: tuple[Path, str] | None = None,
    ) -> None:
        with SessionLocal() as session:
            run = session.scalar(select(BenchmarkRun).where(BenchmarkRun.id == run_id).with_for_update())
            if not run:
                return
            if run.status == RunStatus.cancelled:
                return
            run.status = RunStatus.failed
            run.stage = "Failed"
            run.error = message[:4_000]
            run.completed_at = datetime.now(UTC)
            checkpoint_name = None
            if checkpoint is not None:
                archive_path, archive_sha = checkpoint
                if archive_path.is_file():
                    checkpoint_name = archive_path.name
                    session.add(
                        RunArtifact(
                            run_id=run_id,
                            name=archive_path.name,
                            media_type="application/gzip",
                            path=str(archive_path),
                            sha256=archive_sha,
                            size=archive_path.stat().st_size,
                            metadata_json={
                                "kind": "failure-checkpoint",
                                "resumable": False,
                                "replayable": True,
                            },
                        )
                    )
            append_event(
                session,
                run_id,
                "run.failed",
                {
                    "error": message[:1_000],
                    "checkpoint": checkpoint_name,
                },
            )
            session.commit()


def security_summary(events: list[dict]) -> dict:
    calls = [event for event in events if event.get("kind") == "tool.call"]
    results = [event for event in events if event.get("kind") == "tool.result"]
    policy_violations = [event for event in results if event.get("policy_violation")]
    return {
        "tool_calls": len(calls),
        "policy_violations": len(policy_violations),
        "violation_types": sorted({str(event.get("policy_violation")) for event in policy_violations}),
        "passed": not policy_violations,
    }


def main() -> None:
    Worker().run_forever()


if __name__ == "__main__":
    main()
