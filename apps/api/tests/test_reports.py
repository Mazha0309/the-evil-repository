import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.reports import export_report
from app.database import Base
from app.models import (
    BenchmarkRun,
    ModelProfile,
    ModelProvider,
    RunArtifact,
    RunEvent,
    RunStatus,
    TaskDefinition,
    UserAccount,
    UserRole,
)


def test_detailed_report_exports_replayable_telemetry_without_secrets(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        admin = UserAccount(
            username="report-admin",
            password_hash="not-used",
            role=UserRole.admin,
            enabled=True,
        )
        model = ModelProfile(
            name="Candidate",
            provider=ModelProvider.openai_compatible,
            base_url="https://provider.example/v1",
            model_id="candidate",
            enabled=True,
        )
        task = TaskDefinition(
            slug="telemetry-export",
            version="1.0.0",
            name="Telemetry export",
            description="Export test",
            category="test",
            manifest={"budget": {"hard_seconds": 4_800}},
            enabled=True,
        )
        session.add_all([admin, model, task])
        session.flush()
        run = BenchmarkRun(
            task_id=task.id,
            candidate_model_id=model.id,
            status=RunStatus.running,
            stage="Candidate investigation",
            config={
                "candidate_model_snapshot": {
                    "name": "Candidate",
                    "credential_id": "safe-reference",
                    "api_key": "must-not-export",
                }
            },
            scorecard={"dimensions": {}},
        )
        session.add(run)
        session.flush()
        session.add_all(
            [
                RunEvent(
                    run_id=run.id,
                    sequence=1,
                    kind="model.request",
                    payload={
                        "turn": 1,
                        "context_messages": 2,
                        "context_characters": 512,
                    },
                ),
                RunEvent(
                    run_id=run.id,
                    sequence=2,
                    kind="assistant.message",
                    payload={
                        "turn": 1,
                        "duration_ms": 1_250,
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "content": "visible response",
                    },
                ),
                RunArtifact(
                    run_id=run.id,
                    name="checkpoint.tar.gz",
                    media_type="application/gzip",
                    path=str(tmp_path / "checkpoint.tar.gz"),
                    sha256="a" * 64,
                    size=123,
                    metadata_json={"kind": "failure-checkpoint"},
                ),
            ]
        )
        session.commit()

        response = export_report(run.id, session, admin)
        payload = json.loads(response.body)

    assert payload["export_schema_version"] == 2
    assert payload["run"]["config"]["candidate_model_snapshot"]["api_key"] == (
        "[redacted]"
    )
    assert (
        payload["run"]["config"]["candidate_model_snapshot"]["credential_id"]
        == "safe-reference"
    )
    assert payload["telemetry"]["summary"]["provider"]["logical_turns"] == 1
    assert payload["telemetry"]["provider_turns"][0]["duration_ms"] == 1_250
    assert payload["events"][0]["created_at"] is not None
    assert payload["artifacts"][0]["sha256"] == "a" * 64
    assert payload["privacy"]["credentials_included"] is False
    assert "telemetry.json" in response.headers["content-disposition"]
