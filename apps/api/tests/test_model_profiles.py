import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.model_profiles import delete_model, list_models
from app.api.runs import create_run
from app.database import Base
from app.model_identity import model_snapshot
from app.models import (
    BenchmarkRun,
    ModelProfile,
    ModelProvider,
    RunStatus,
    TaskDefinition,
    UserAccount,
    UserModelAccess,
    UserRole,
)
from app.schemas import RunCreate


def make_user() -> UserAccount:
    return UserAccount(
        username="model-owner",
        password_hash="not-used",
        role=UserRole.user,
        enabled=True,
    )


def make_model(name: str) -> ModelProfile:
    return ModelProfile(
        name=name,
        provider=ModelProvider.openai_compatible,
        base_url="https://provider.example/v1",
        model_id=f"{name}-model",
        encrypted_api_key="encrypted-secret",
        native_tools=True,
        parameters={"temperature": 0.2},
        enabled=True,
    )


def make_task() -> TaskDefinition:
    return TaskDefinition(
        slug="archive-test",
        version="1.0.0",
        name="Archive test",
        description="Test model lifecycle",
        category="test",
        manifest={},
        enabled=True,
    )


def test_delete_archives_profile_and_preserves_historical_run_identity() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = make_user()
        target = make_model("retired")
        other = make_model("active")
        task = make_task()
        session.add_all([user, target, other, task])
        session.flush()
        session.add_all(
            [
                UserModelAccess(
                    user_id=user.id,
                    model_profile_id=target.id,
                ),
                UserModelAccess(
                    user_id=user.id,
                    model_profile_id=other.id,
                ),
            ]
        )
        candidate_run = BenchmarkRun(
            task_id=task.id,
            candidate_model_id=target.id,
            status=RunStatus.completed,
            config={},
        )
        existing_candidate_snapshot = model_snapshot(other)
        judge_run = BenchmarkRun(
            task_id=task.id,
            candidate_model_id=other.id,
            judge_model_id=target.id,
            status=RunStatus.failed,
            config={"candidate_model_snapshot": existing_candidate_snapshot},
        )
        session.add_all([candidate_run, judge_run])
        session.commit()

        target_id = target.id
        candidate_run_id = candidate_run.id
        judge_run_id = judge_run.id
        delete_model(target_id, session, user)
        session.expire_all()

        archived = session.get(ModelProfile, target_id)
        assert archived is not None
        assert archived.archived_at is not None
        assert archived.enabled is False
        assert archived.encrypted_api_key is None
        assert archived.base_url == "https://archived.invalid"
        assert archived.native_tools is False
        assert archived.parameters == {}

        stored_candidate_run = session.get(BenchmarkRun, candidate_run_id)
        stored_judge_run = session.get(BenchmarkRun, judge_run_id)
        assert stored_candidate_run is not None
        assert stored_judge_run is not None
        assert stored_candidate_run.config["candidate_model_snapshot"] == {
            "profile_id": str(target_id),
            "name": "retired",
            "provider": "openai_compatible",
            "model_id": "retired-model",
        }
        assert stored_judge_run.config["judge_model_snapshot"] == {
            "profile_id": str(target_id),
            "name": "retired",
            "provider": "openai_compatible",
            "model_id": "retired-model",
        }
        assert stored_judge_run.config["candidate_model_snapshot"] == existing_candidate_snapshot
        assert [profile.name for profile in list_models(session, user)] == ["active"]


def test_delete_rejects_profile_used_by_active_run() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = make_user()
        target = make_model("busy")
        task = make_task()
        session.add_all([user, target, task])
        session.flush()
        session.add(
            UserModelAccess(
                user_id=user.id,
                model_profile_id=target.id,
            )
        )
        session.add(
            BenchmarkRun(
                task_id=task.id,
                candidate_model_id=target.id,
                status=RunStatus.running,
                config={"candidate_model_snapshot": model_snapshot(target)},
            )
        )
        session.commit()

        with pytest.raises(HTTPException) as error:
            delete_model(target.id, session, user)

        assert error.value.status_code == 409
        assert "1 active run(s)" in error.value.detail
        session.refresh(target)
        assert target.archived_at is None
        assert target.enabled is True
        assert target.encrypted_api_key == "encrypted-secret"


def test_archived_profile_cannot_be_selected_for_a_new_run() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = make_user()
        target = make_model("retired-candidate")
        task = make_task()
        session.add_all([user, target, task])
        session.flush()
        session.add(
            UserModelAccess(
                user_id=user.id,
                model_profile_id=target.id,
            )
        )
        session.commit()

        delete_model(target.id, session, user)

        with pytest.raises(HTTPException) as error:
            create_run(
                RunCreate(
                    task_id=task.id,
                    candidate_model_id=target.id,
                ),
                session,
                user,
            )

        assert error.value.status_code == 400
        assert error.value.detail == "Unknown task or candidate model"
