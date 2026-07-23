from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import (
    BenchmarkRun,
    ModelProfile,
    RunnerHeartbeat,
    RunStatus,
    TaskDefinition,
    UserAccount,
    UserModelAccess,
    UserRole,
    UserRunAccess,
)
from app.schemas import DashboardSummary
from app.security import current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> DashboardSummary:
    run_scope = []
    model_scope = [ModelProfile.archived_at.is_(None)]
    if user.role != UserRole.admin:
        run_scope.append(BenchmarkRun.id.in_(select(UserRunAccess.run_id).where(UserRunAccess.user_id == user.id)))
        model_scope.append(
            ModelProfile.id.in_(select(UserModelAccess.model_profile_id).where(UserModelAccess.user_id == user.id))
        )
    total_runs = session.scalar(select(func.count(BenchmarkRun.id)).where(*run_scope)) or 0
    active_runs = (
        session.scalar(
            select(func.count(BenchmarkRun.id)).where(
                BenchmarkRun.status.in_([RunStatus.queued, RunStatus.preparing, RunStatus.running, RunStatus.scoring]),
                *run_scope,
            )
        )
        or 0
    )
    completed_runs = (
        session.scalar(
            select(func.count(BenchmarkRun.id)).where(
                BenchmarkRun.status == RunStatus.completed,
                *run_scope,
            )
        )
        or 0
    )
    average_score = session.scalar(
        select(func.avg(BenchmarkRun.score)).where(
            BenchmarkRun.status == RunStatus.completed,
            *run_scope,
        )
    )
    heartbeat = session.get(RunnerHeartbeat, "default")
    heartbeat_at = heartbeat.updated_at if heartbeat else None
    if heartbeat_at and heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=UTC)
    runner_alive = bool(heartbeat_at and heartbeat_at >= datetime.now(UTC) - timedelta(seconds=15))
    return DashboardSummary(
        tasks=(
            session.scalar(
                select(func.count(TaskDefinition.id)).where(
                    TaskDefinition.enabled.is_(True)
                )
            )
            or 0
        ),
        models=session.scalar(select(func.count(ModelProfile.id)).where(*model_scope)) or 0,
        total_runs=total_runs,
        active_runs=active_runs,
        completed_runs=completed_runs,
        average_score=float(average_score) if average_score is not None else None,
        docker_ready=bool(runner_alive and heartbeat and heartbeat.docker_ready),
        runner_enabled=runner_alive,
    )
