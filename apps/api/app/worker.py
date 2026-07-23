import hashlib
import logging
import tempfile
import threading
import time
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path

import docker
from sqlalchemy import select

from app.config import get_settings
from app.crypto import SecretBox
from app.database import SessionLocal, create_schema
from app.events import append_event
from app.models import (
    BenchmarkRun,
    ModelProfile,
    RunArtifact,
    RunEvent,
    RunnerHeartbeat,
    RunStatus,
    TaskDefinition,
)
from app.runner.engine import AgentEngine
from app.runner.faults import FaultController
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

    def heartbeat_forever(self) -> None:
        while True:
            ready = False
            detail = "Docker daemon unavailable"
            client: docker.DockerClient | None = None
            try:
                client = docker.DockerClient(base_url=settings.docker_host)
                client.ping()
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
        started = time.monotonic()
        try:
            with SessionLocal() as session:
                run = session.get(BenchmarkRun, run_id)
                assert run is not None
                task = session.get(TaskDefinition, run.task_id)
                profile = session.get(ModelProfile, run.candidate_model_id)
                if not task or not profile:
                    raise RuntimeError("Run references missing task/model")
                scenario_root = settings.scenarios_root / task.slug
                encrypted_key = profile.encrypted_api_key
                append_event(
                    session,
                    run_id,
                    "scenario.loaded",
                    {"root": str(scenario_root), "slug": task.slug, "version": task.version},
                )
                session.commit()

            scenario = load_scenario(scenario_root)
            with tempfile.TemporaryDirectory(prefix=f"evil-{run_id}-") as temporary:
                prepared = scenario.prepare(Path(temporary), scale=1.0)
                with SessionLocal() as session:
                    run = session.get(BenchmarkRun, run_id)
                    assert run is not None
                    run.status = RunStatus.running
                    run.stage = "Candidate investigation"
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
                box = SecretBox(settings.app_secret)
                client = ModelClient(profile, box.decrypt(encrypted_key))
                faults = FaultController.load([Path(path) for path in prepared.private_state["fault_scripts"]])
                engine = AgentEngine(
                    run_id=run_id,
                    client=client,
                    sandbox=sandbox,
                    prepared=prepared,
                    faults=faults,
                )
                result = scenario.run(prepared, engine.run)
                result.artifacts.update(
                    {
                        "dead-letter.diff": sandbox.git_diff("dead-letter"),
                        "dead-letter.status": sandbox.git_status("dead-letter"),
                        "palimpsest.diff": sandbox.git_diff("palimpsest"),
                        "palimpsest.status": sandbox.git_status("palimpsest"),
                        "INVESTIGATION.md": (
                            sandbox.collect_text("INVESTIGATION.md")
                            or sandbox.collect_text("dead-letter/INVESTIGATION.md")
                        ),
                    }
                )
                static = sandbox.static_check()
                regression = sandbox.hidden_regression()
                mutation = sandbox.hidden_mutation()
                golden = sandbox.hidden_golden_replay(Path(prepared.private_state["hidden_database_sql"]))
                stats = sandbox.stats()
                result.private_state.update(
                    {
                        "hidden_verification_passed": (
                            static.status == "ok"
                            and regression.status == "ok"
                            and mutation.status == "ok"
                            and golden.status == "ok"
                        ),
                        "static_check": static.model_dump(mode="json"),
                        "regression": regression.model_dump(mode="json"),
                        "mutation": mutation.model_dump(mode="json"),
                        "golden_replay": golden.model_dump(mode="json"),
                        "resource_check": stats,
                        "security_check": security_summary(result.events),
                    }
                )
                with SessionLocal() as session:
                    recorded_events = session.scalars(
                        select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.sequence)
                    ).all()
                    result.events = [
                        {"kind": event.kind, "sequence": event.sequence, **event.payload} for event in recorded_events
                    ]

                with SessionLocal() as session:
                    run = session.get(BenchmarkRun, run_id)
                    assert run is not None
                    run.status = RunStatus.scoring
                    run.stage = "Hidden judge pipeline"
                    append_event(session, run_id, "run.scoring", {"stage": run.stage})
                    session.commit()

                scorecard = scenario.grade(prepared, result)
                archive_path = Path(settings.artifact_root) / f"{run_id}.tar.gz"
                scenario.archive(prepared, result, archive_path)
                archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
                self.complete(run_id, result, scorecard, archive_path, archive_sha)
        except Exception as exc:
            logger.error("Run %s failed: %s\n%s", run_id, exc, traceback.format_exc())
            self.fail(run_id, str(exc))
        finally:
            if sandbox:
                sandbox.stop()
            logger.info("Run %s finished in %.2fs", run_id, time.monotonic() - started)

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
    policy_violations = [event for event in results if event.get("policy_violation") == "host_or_network_probe"]
    return {
        "tool_calls": len(calls),
        "policy_violations": len(policy_violations),
        "passed": not policy_violations,
    }


def main() -> None:
    Worker().run_forever()


if __name__ == "__main__":
    main()
