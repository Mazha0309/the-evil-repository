from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import BenchmarkRun, ModelProfile, RunnerHeartbeat, RunStatus, TaskDefinition
from app.schemas import DashboardSummary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(session: Session = Depends(get_session)) -> DashboardSummary:
    total_runs = session.scalar(select(func.count(BenchmarkRun.id))) or 0
    active_runs = (
        session.scalar(
            select(func.count(BenchmarkRun.id)).where(
                BenchmarkRun.status.in_([RunStatus.queued, RunStatus.preparing, RunStatus.running, RunStatus.scoring])
            )
        )
        or 0
    )
    completed_runs = (
        session.scalar(select(func.count(BenchmarkRun.id)).where(BenchmarkRun.status == RunStatus.completed)) or 0
    )
    average_score = session.scalar(
        select(func.avg(BenchmarkRun.score)).where(BenchmarkRun.status == RunStatus.completed)
    )
    heartbeat = session.get(RunnerHeartbeat, "default")
    heartbeat_at = heartbeat.updated_at if heartbeat else None
    if heartbeat_at and heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=UTC)
    runner_alive = bool(heartbeat_at and heartbeat_at >= datetime.now(UTC) - timedelta(seconds=15))
    return DashboardSummary(
        tasks=session.scalar(select(func.count(TaskDefinition.id))) or 0,
        models=session.scalar(select(func.count(ModelProfile.id))) or 0,
        total_runs=total_runs,
        active_runs=active_runs,
        completed_runs=completed_runs,
        average_score=float(average_score) if average_score is not None else None,
        docker_ready=bool(runner_alive and heartbeat and heartbeat.docker_ready),
        runner_enabled=runner_alive,
    )
