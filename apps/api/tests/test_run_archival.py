import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.dashboard import dashboard_summary
from app.api.runs import archive_run, get_run, list_runs
from app.database import Base
from app.models import (
    BenchmarkRun,
    ModelProfile,
    ModelProvider,
    RunEvent,
    RunStatus,
    TaskDefinition,
    UserAccount,
    UserModelAccess,
    UserRole,
    UserRunAccess,
)


def seed_run(
    session: Session,
    *,
    status: RunStatus,
) -> tuple[UserAccount, BenchmarkRun]:
    user = UserAccount(
        username=f"owner-{status.value}",
        password_hash="not-used",
        role=UserRole.user,
        enabled=True,
    )
    model = ModelProfile(
        name=f"model-{status.value}",
        provider=ModelProvider.openai_compatible,
        base_url="https://provider.example/v1",
        model_id="candidate",
        enabled=True,
    )
    task = TaskDefinition(
        slug=f"archive-{status.value}",
        version="1.0.0",
        name="Archive test",
        description="Test run archival",
        category="test",
        manifest={},
        enabled=True,
    )
    session.add_all([user, model, task])
    session.flush()
    run = BenchmarkRun(
        task_id=task.id,
        candidate_model_id=model.id,
        status=status,
        stage=status.value,
        score=777 if status == RunStatus.completed else None,
        scorecard={"dimensions": {}},
        config={},
    )
    session.add(run)
    session.flush()
    session.add_all(
        [
            UserModelAccess(
                user_id=user.id,
                model_profile_id=model.id,
            ),
            UserRunAccess(
                user_id=user.id,
                run_id=run.id,
            ),
            RunEvent(
                run_id=run.id,
                sequence=1,
                kind="run.completed",
                payload={},
            ),
        ]
    )
    session.commit()
    return user, run


def test_archive_run_hides_terminal_result_without_deleting_evidence() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user, run = seed_run(session, status=RunStatus.completed)
        run_id = run.id

        archive_run(run_id, session, user)
        session.expire_all()

        stored = session.get(BenchmarkRun, run_id)
        assert stored is not None
        assert stored.archived_at is not None
        assert stored.status == RunStatus.completed
        assert stored.score == 777
        assert list_runs(session, user) == []
        summary = dashboard_summary(session, user)
        assert summary.total_runs == 0
        assert summary.completed_runs == 0
        assert summary.average_score is None
        assert session.get(
            UserRunAccess,
            {"user_id": user.id, "run_id": run_id},
        ) is not None
        events = list(
            session.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id)
                .order_by(RunEvent.sequence)
            ).all()
        )
        assert [event.kind for event in events] == [
            "run.completed",
            "run.archived",
        ]

        with pytest.raises(HTTPException) as error:
            get_run(run_id, session, user)
        assert error.value.status_code == 404


def test_archive_run_rejects_active_result() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user, run = seed_run(session, status=RunStatus.running)

        with pytest.raises(HTTPException) as error:
            archive_run(run.id, session, user)

        assert error.value.status_code == 409
        assert "finish or be cancelled" in error.value.detail
        session.refresh(run)
        assert run.archived_at is None


def test_dashboard_average_excludes_censored_completed_run() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user, run = seed_run(session, status=RunStatus.completed)
        run.scorecard = {
            "resources": {"hard_limits_crossed": ["active_time"]},
        }
        session.commit()

        summary = dashboard_summary(session, user)

        assert summary.completed_runs == 1
        assert summary.average_score is None
