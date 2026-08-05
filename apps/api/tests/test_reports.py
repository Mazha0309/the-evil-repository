import hashlib
import io
import json
import tarfile
import uuid
from collections.abc import Generator
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth, diffs, reports
from app.api.reports import build_report_payload, export_report
from app.database import Base, get_session
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

TOOL_ARGUMENTS = "path=README.md&lines=1,40&" + "x" * 300
TOOL_OUTPUT = "# The Evil Repository\n" + "y" * 500

def build_client() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=Session,
    )
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(reports.router, prefix="/api/v1")

    def override_session() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), testing_session

def seed_run(
    sessions: sessionmaker[Session],
    *,
    with_tools: bool = True,
    tool_arguments: object = TOOL_ARGUMENTS,
) -> uuid.UUID:
    with sessions() as session:
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
        session.add_all([model, task])
        session.flush()
        run = BenchmarkRun(
            task_id=task.id,
            candidate_model_id=model.id,
            status=RunStatus.completed,
            stage="Candidate investigation",
            config={"candidate_model_snapshot": {"provider": "openai_compatible"}},
            scorecard={
                "score": 100,
                "maximum": 100,
                "dimensions": {},
                "overtime_penalty": {"total_penalty": 0.5, "score_after": 99.5},
            },
        )
        session.add(run)
        session.flush()
        events = [
            RunEvent(
                run_id=run.id,
                sequence=1,
                kind="run.turn.begin",
                payload={"turn": 1},
            )
        ]
        if with_tools:
            events.extend(
                [
                    RunEvent(
                        run_id=run.id,
                        sequence=2,
                        kind="tool.call",
                        payload={
                            "turn": 1,
                            "call_id": "call-1",
                            "name": "read_file",
                            "arguments": tool_arguments,
                        },
                    ),
                    RunEvent(
                        run_id=run.id,
                        sequence=3,
                        kind="tool.result",
                        payload={
                            "turn": 1,
                            "call_id": "call-1",
                            "output": TOOL_OUTPUT,
                            "status": "ok",
                        },
                    ),
                ]
            )
        events.extend(
            [
                RunEvent(
                    run_id=run.id,
                    sequence=4,
                    kind="run.turn.end",
                    payload={"turn": 1, "duration_ms": 100},
                ),
                RunEvent(
                    run_id=run.id,
                    sequence=5,
                    kind="run.budget_adjusted",
                    payload={
                        "field": "hard_tool_calls",
                        "requested_at": "2026-08-05T10:00:00+00:00",
                        "applied_at": "2026-08-05T10:00:01+00:00",
                    },
                ),
            ]
        )
        session.add_all(events)
        session.commit()
        return run.id

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
            scorecard={
                "dimensions": {},
                "overtime_penalty": {"total_penalty": 0.25},
            },
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

        response = export_report(
            run.id,
            include="compact",
            session=session,
            user=admin,
        )
        payload = json.loads(response.body)

    assert payload["export_schema_version"] == 3
    assert payload["run"]["config"]["candidate_model_snapshot"]["api_key"] == ("[redacted]")
    assert payload["run"]["config"]["candidate_model_snapshot"]["credential_id"] == "safe-reference"
    assert payload["telemetry"]["summary"]["provider"]["logical_turns"] == 1
    assert payload["telemetry"]["provider_turns"][0]["duration_ms"] == 1_250
    assert payload["run"]["tokens"]["available"] is True
    assert payload["events"][0]["created_at"] is not None
    assert payload["artifacts"][0]["sha256"] == "a" * 64
    assert payload["privacy"]["credentials_included"] is False
    assert "telemetry.json" in response.headers["content-disposition"]
    assert payload["turn_summary"] == {
        "total_turns": 0,
        "completed_turns": 0,
        "average_duration_ms": None,
        "max_duration_ms": None,
    }
    assert payload["budget_adjustments"] == {
        "count": 0,
        "fields": [],
        "first_at": None,
        "last_at": None,
    }
    assert payload["overtime_penalty"] == {"total_penalty": 0.25}
    assert payload["diffs"] == []

def test_report_v3_compact_events_and_lean_fields() -> None:
    client, sessions = build_client()
    setup = client.post(
        "/api/v1/auth/setup",
        json={
            "username": "report-admin",
            "password": "correct horse battery staple",
        },
    )
    assert setup.status_code == 201
    run_id = seed_run(sessions)

    response = client.get(f"/api/v1/reports/{run_id}")
    payload = response.json()

    assert response.status_code == 200
    assert payload["export_schema_version"] == 3
    tool_calls = [e for e in payload["events"] if e.get("kind") == "tool.call"]
    tool_results = [e for e in payload["events"] if e.get("kind") == "tool.result"]
    assert tool_calls
    assert "arguments" not in tool_calls[0]
    assert "arguments_sha256" in tool_calls[0]
    assert "arguments_size_bytes" in tool_calls[0]
    assert "arguments_preview" in tool_calls[0]
    assert tool_calls[0]["arguments_preview"] == TOOL_ARGUMENTS[:200]
    assert "output" not in tool_results[0]
    assert "output_sha256" in tool_results[0]
    assert "output_size_bytes" in tool_results[0]
    assert "output_preview" in tool_results[0]
    assert payload["turn_summary"] == {
        "total_turns": 1,
        "completed_turns": 1,
        "average_duration_ms": 100.0,
        "max_duration_ms": 100.0,
    }
    assert payload["budget_adjustments"] == {
        "count": 1,
        "fields": ["hard_tool_calls"],
        "first_at": "2026-08-05T10:00:00+00:00",
        "last_at": "2026-08-05T10:00:00+00:00",
    }
    assert payload["overtime_penalty"]["total_penalty"] == 0.5

def test_report_v3_full_events_query_param() -> None:
    client, sessions = build_client()
    setup = client.post(
        "/api/v1/auth/setup",
        json={
            "username": "report-admin",
            "password": "correct horse battery staple",
        },
    )
    assert setup.status_code == 201
    run_id = seed_run(sessions)

    response = client.get(f"/api/v1/reports/{run_id}?include=full-events")
    payload = response.json()

    assert response.status_code == 200
    assert payload["export_schema_version"] == 3
    tool_calls = [e for e in payload["events"] if e.get("kind") == "tool.call"]
    assert tool_calls
    assert "arguments" in tool_calls[0]
    assert tool_calls[0]["arguments"] == TOOL_ARGUMENTS
    assert "arguments_sha256" not in tool_calls[0]

def test_report_v3_diffs_manifest_from_archive(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(diffs.settings, "artifact_root", str(tmp_path))
    client, sessions = build_client()
    setup = client.post(
        "/api/v1/auth/setup",
        json={
            "username": "report-admin",
            "password": "correct horse battery staple",
        },
    )
    assert setup.status_code == 201
    run_id = seed_run(sessions)
    diff_text = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,1 +1,2 @@\n"
        "- old\n"
        "+ new\n"
    )
    diff_sha256 = hashlib.sha256(diff_text.encode()).hexdigest()
    with tarfile.open(tmp_path / f"{run_id}.tar.gz", "w:gz") as archive:
        data = diff_text.encode()
        info = tarfile.TarInfo("artifacts/dead-letter.diff")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    with sessions() as session:
        session.add(
            RunArtifact(
                run_id=run_id,
                name="dead-letter.diff",
                media_type="text/plain",
                path="unused",
                sha256=diff_sha256,
                size=len(data),
                metadata_json={},
            )
        )
        session.commit()

    response = client.get(f"/api/v1/reports/{run_id}")
    payload = response.json()

    assert payload["export_schema_version"] == 3
    assert payload["diffs"] == [
        {
            "repo": "dead-letter",
            "added_lines": 1,
            "removed_lines": 1,
            "file_count": 1,
            "sha256": diff_sha256,
        }
    ]

def test_report_v3_compact_events_hashes_dict_arguments() -> None:
    client, sessions = build_client()
    setup = client.post(
        "/api/v1/auth/setup",
        json={
            "username": "report-admin",
            "password": "correct horse battery staple",
        },
    )
    assert setup.status_code == 201
    dict_arguments = {
        "path": "README.md",
        "lines": [1, 40],
        "nested": {"flag": True},
    }
    run_id = seed_run(sessions, tool_arguments=dict_arguments)

    response = client.get(f"/api/v1/reports/{run_id}")
    payload = response.json()

    assert payload["export_schema_version"] == 3
    tool_calls = [e for e in payload["events"] if e.get("kind") == "tool.call"]
    assert tool_calls
    assert "arguments" not in tool_calls[0]
    assert "arguments_sha256" in tool_calls[0]
    assert "arguments_size_bytes" in tool_calls[0]
    assert "arguments_preview" in tool_calls[0]
    expected = json.dumps(dict_arguments, ensure_ascii=False, sort_keys=True)
    assert tool_calls[0]["arguments_preview"] == expected[:200]
    assert tool_calls[0]["arguments_size_bytes"] == len(expected.encode())

def test_build_report_payload_matches_export_endpoint_payload() -> None:
    client, sessions = build_client()
    setup = client.post(
        "/api/v1/auth/setup",
        json={
            "username": "report-admin",
            "password": "correct horse battery staple",
        },
    )
    assert setup.status_code == 201
    run_id = seed_run(sessions)

    response = client.get(f"/api/v1/reports/{run_id}")
    assert response.status_code == 200
    with sessions() as session:
        payload = build_report_payload(run_id, session, include="compact")

    payload.pop("generated_at")
    expected = response.json()
    expected.pop("generated_at")
    assert payload == expected

