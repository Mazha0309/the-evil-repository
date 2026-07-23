import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.runs as runs_module
from app.api.runs import download_run_artifact, list_run_artifacts
from app.database import Base
from app.models import (
    BenchmarkRun,
    RunArtifact,
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
