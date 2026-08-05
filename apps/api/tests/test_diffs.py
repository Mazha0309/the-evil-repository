import io
import tarfile
import uuid
from collections.abc import Generator
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.diffs as diffs_module
from app.api import auth, diffs
from app.database import Base, get_session
from app.models import BenchmarkRun, RunStatus


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
    app.include_router(diffs.router, prefix="/api/v1")

    def override_session() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), testing_session


def write_archive(artifact_root: Path, run_id: uuid.UUID) -> None:
    archive = artifact_root / f"{run_id}.tar.gz"

    def add(tar: tarfile.TarFile, name: str, content: str) -> None:
        data = content.encode()
        info = tarfile.TarInfo(f"artifacts/{name}")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    with tarfile.open(archive, "w:gz") as tar:
        add(
            tar,
            "dead-letter.diff",
            "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1,1 +1,2 @@\n- old\n+ new\n",
        )
        add(tar, "dead-letter.status", " M README.md\n")


def test_run_diffs_returns_repo_diffs_and_stats_from_archive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(diffs_module.settings, "artifact_root", str(tmp_path))
    client, sessions = build_client()

    setup = client.post(
        "/api/v1/auth/setup",
        json={
            "username": "diffs-admin",
            "password": "correct horse battery staple",
        },
    )
    assert setup.status_code == 201
    run_id = uuid.uuid4()
    with sessions() as session:
        session.add(
            BenchmarkRun(
                id=run_id,
                task_id=uuid.uuid4(),
                candidate_model_id=uuid.uuid4(),
                status=RunStatus.failed,
                stage="Failed",
                config={},
            )
        )
        session.commit()
    write_archive(tmp_path, run_id)

    response = client.get(f"/api/v1/runs/{run_id}/diffs")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["repo"] == "dead-letter"
    assert body[0]["added_lines"] == 1
    assert body[0]["removed_lines"] == 1
    assert body[0]["file_count"] == 1
    assert "diff --git" in body[0]["diff_text"]
    assert body[0]["status_text"].strip()


def test_run_diffs_returns_404_when_no_archive_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(diffs_module.settings, "artifact_root", str(tmp_path))
    client, sessions = build_client()

    setup = client.post(
        "/api/v1/auth/setup",
        json={
            "username": "diffs-admin",
            "password": "correct horse battery staple",
        },
    )
    assert setup.status_code == 201
    run_id = uuid.uuid4()
    with sessions() as session:
        session.add(
            BenchmarkRun(
                id=run_id,
                task_id=uuid.uuid4(),
                candidate_model_id=uuid.uuid4(),
                status=RunStatus.failed,
                stage="Failed",
                config={},
            )
        )
        session.commit()

    response = client.get(f"/api/v1/runs/{run_id}/diffs")

    assert response.status_code == 404
