import io
import tarfile
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.runs as runs_module
from app.api import auth, runs
from app.api.runs import download_run_artifact, list_run_artifacts
from app.database import Base, get_session
from app.models import (
    BenchmarkRun,
    RunArtifact,
    RunEvent,
    RunStatus,
    UserAccount,
    UserRole,
)


def build_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=Session,
    )


def build_client() -> tuple[TestClient, sessionmaker[Session]]:
    sessions = build_session_factory()
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(runs.router, prefix="/api/v1")

    def override_session() -> Generator[Session, None, None]:
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), sessions


def write_run_archive(artifact_root: Path, run_id: uuid.UUID) -> None:
    archive = artifact_root / f"{run_id}.tar.gz"

    def add(tar: tarfile.TarFile, name: str, content: str) -> None:
        data = content.encode()
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    with tarfile.open(archive, "w:gz") as tar:
        add(tar, "run.json", '{"archive_schema_version": 3}')
        add(tar, "events.jsonl", '{"sequence": 1}\n')
        add(tar, "telemetry/summary.json", '{"event_count": 1}')
        add(tar, "artifacts/note.txt", "hello archive")


def test_run_artifact_can_be_listed_and_downloaded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions = build_session_factory()
    run_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    archive = tmp_path / "artifacts" / "checkpoint.tar.gz"
    archive.parent.mkdir()
    archive.write_bytes(b"forensic checkpoint")
    monkeypatch.setattr(
        runs_module.settings,
        "artifact_root",
        str(archive.parent),
    )
    with sessions() as session:
        admin = UserAccount(
            username="admin",
            password_hash="unused",
            role=UserRole.admin,
        )
        session.add_all(
            [
                admin,
                BenchmarkRun(
                    id=run_id,
                    task_id=uuid.uuid4(),
                    candidate_model_id=uuid.uuid4(),
                    status=RunStatus.failed,
                    stage="Failed",
                    config={},
                ),
                RunArtifact(
                    id=artifact_id,
                    run_id=run_id,
                    name=archive.name,
                    media_type="application/gzip",
                    path=str(archive),
                    sha256="a" * 64,
                    size=archive.stat().st_size,
                    metadata_json={"kind": "failure-checkpoint"},
                ),
            ]
        )
        session.commit()

        artifacts = list_run_artifacts(run_id, session, admin)
        response = download_run_artifact(
            run_id,
            artifact_id,
            session,
            admin,
        )

        assert [item.id for item in artifacts] == [artifact_id]
        assert Path(response.path) == archive
        assert response.media_type == "application/gzip"
        assert response.filename == archive.name


def test_run_artifact_download_rejects_path_outside_artifact_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions = build_session_factory()
    run_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    outside = tmp_path / "outside.tar.gz"
    outside.write_bytes(b"must not be served")
    monkeypatch.setattr(
        runs_module.settings,
        "artifact_root",
        str(artifact_root),
    )
    with sessions() as session:
        admin = UserAccount(
            username="admin",
            password_hash="unused",
            role=UserRole.admin,
        )
        session.add_all(
            [
                admin,
                BenchmarkRun(
                    id=run_id,
                    task_id=uuid.uuid4(),
                    candidate_model_id=uuid.uuid4(),
                    status=RunStatus.failed,
                    stage="Failed",
                    config={},
                ),
                RunArtifact(
                    id=artifact_id,
                    run_id=run_id,
                    name=outside.name,
                    media_type="application/gzip",
                    path=str(outside),
                    sha256="b" * 64,
                    size=outside.stat().st_size,
                    metadata_json={"kind": "failure-checkpoint"},
                ),
            ]
        )
        session.commit()

        with pytest.raises(HTTPException) as caught:
            download_run_artifact(
                run_id,
                artifact_id,
                session,
                admin,
            )

        assert caught.value.status_code == 404


def test_run_export_endpoint_returns_lean_json_and_filtered_tar_gz(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(runs_module.settings, "artifact_root", str(tmp_path))
    client, sessions = build_client()
    setup = client.post(
        "/api/v1/auth/setup",
        json={
            "username": "export-admin",
            "password": "correct horse battery staple",
        },
    )
    assert setup.status_code == 201
    run_id = uuid.uuid4()
    with sessions() as session:
        session.add_all(
            [
                BenchmarkRun(
                    id=run_id,
                    task_id=uuid.uuid4(),
                    candidate_model_id=uuid.uuid4(),
                    status=RunStatus.failed,
                    stage="Failed",
                    config={},
                ),
                RunEvent(
                    run_id=run_id,
                    sequence=1,
                    kind="tool.call",
                    payload={
                        "turn": 1,
                        "call_id": "call-1",
                        "name": "read_file",
                        "arguments": {"path": "README.md"},
                    },
                ),
            ]
        )
        session.commit()
    write_run_archive(tmp_path, run_id)

    response = client.get(f"/api/v1/runs/{run_id}/export?format=json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["export_schema_version"] == 3
    tool_calls = [e for e in payload["events"] if e.get("kind") == "tool.call"]
    assert tool_calls
    assert "arguments" not in tool_calls[0]

    response = client.get(
        f"/api/v1/runs/{run_id}/export?format=json&include=full-events"
    )
    assert response.status_code == 200
    payload = response.json()
    tool_calls = [e for e in payload["events"] if e.get("kind") == "tool.call"]
    assert tool_calls[0]["arguments"] == {"path": "README.md"}

    response = client.get(
        f"/api/v1/runs/{run_id}/export?format=tar.gz&include=all"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/gzip")
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
        names = set(archive.getnames())
    assert {
        "run.json",
        "events.jsonl",
        "telemetry/summary.json",
        "artifacts/note.txt",
    } <= names

    response = client.get(
        f"/api/v1/runs/{run_id}/export?format=tar.gz&include=telemetry"
    )
    assert response.status_code == 200
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
        names = archive.getnames()
    assert names == ["telemetry/summary.json"]
