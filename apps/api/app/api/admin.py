import os
import shutil
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.auth import change_username, create_user
from app.config import get_settings
from app.database import get_session
from app.models import (
    BenchmarkRun,
    ModelProfile,
    PlatformSettings,
    RunnerHeartbeat,
    RunStatus,
    ServiceTelemetry,
    UserAccount,
    UserRole,
    UserSession,
)
from app.platform import ensure_platform_settings
from app.schemas import (
    AdminSummary,
    AdminUserCreate,
    AdminUserUpdate,
    PlatformSettingsRead,
    PlatformSettingsUpdate,
    ServerMonitor,
    UserRead,
)
from app.security import admin_csrf, admin_user, aware, hash_password, session_id

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/summary", response_model=AdminSummary)
def admin_summary(
    session: Session = Depends(get_session),
    _: UserAccount = Depends(admin_user),
) -> AdminSummary:
    return AdminSummary(
        users=count(session, UserAccount.id),
        enabled_users=count(session, UserAccount.id, UserAccount.enabled.is_(True)),
        admins=count(session, UserAccount.id, UserAccount.role == UserRole.admin),
        models=count(session, ModelProfile.id),
        total_runs=count(session, BenchmarkRun.id),
        active_runs=count(
            session,
            BenchmarkRun.id,
            BenchmarkRun.status.in_([RunStatus.queued, RunStatus.preparing, RunStatus.running, RunStatus.scoring]),
        ),
    )


@router.get("/users", response_model=list[UserRead])
def list_users(
    session: Session = Depends(get_session),
    _: UserAccount = Depends(admin_user),
) -> list[UserAccount]:
    return list(session.scalars(select(UserAccount).order_by(UserAccount.created_at)).all())


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AdminUserCreate,
    session: Session = Depends(get_session),
    _: UserAccount = Depends(admin_csrf),
) -> UserAccount:
    user = create_user(
        session,
        username=payload.username,
        password=payload.password,
        role=payload.role,
        enabled=payload.enabled,
    )
    session.commit()
    session.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserRead)
def update_account(
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
    request: Request,
    session: Session = Depends(get_session),
    admin: UserAccount = Depends(admin_csrf),
) -> UserAccount:
    target = session.get(UserAccount, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Account not found")
    if target.id == admin.id and (
        payload.enabled is False or payload.role is not None and payload.role != UserRole.admin
    ):
        raise HTTPException(status_code=400, detail="Use another administrator to change your own access")
    if target.role == UserRole.admin and (
        payload.enabled is False or payload.role is not None and payload.role != UserRole.admin
    ):
        enabled_admins = count(
            session,
            UserAccount.id,
            UserAccount.role == UserRole.admin,
            UserAccount.enabled.is_(True),
        )
        if enabled_admins <= 1:
            raise HTTPException(status_code=400, detail="The last enabled administrator cannot be removed")
    if payload.username is not None:
        change_username(session, target, payload.username)
    if payload.role is not None:
        target.role = payload.role
    if payload.enabled is not None:
        target.enabled = payload.enabled
    if payload.password is not None:
        target.password_hash = hash_password(payload.password)
        revoke_user_sessions(session, target.id)
    if payload.enabled is False:
        revoke_user_sessions(session, target.id)
    session.commit()
    session.refresh(target)
    return target


@router.post("/users/{user_id}/revoke-sessions", status_code=status.HTTP_204_NO_CONTENT)
def revoke_account_sessions(
    user_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    admin: UserAccount = Depends(admin_csrf),
) -> None:
    target = session.get(UserAccount, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Account not found")
    preserve = session_id(request) if target.id == admin.id else None
    revoke_user_sessions(session, target.id, preserve=preserve)
    session.commit()


@router.get("/settings", response_model=PlatformSettingsRead)
def get_platform_settings(
    session: Session = Depends(get_session),
    _: UserAccount = Depends(admin_user),
) -> PlatformSettings:
    settings = ensure_platform_settings(session)
    session.commit()
    return settings


@router.patch("/settings", response_model=PlatformSettingsRead)
def update_platform_settings(
    payload: PlatformSettingsUpdate,
    session: Session = Depends(get_session),
    admin: UserAccount = Depends(admin_csrf),
) -> PlatformSettings:
    settings = ensure_platform_settings(session)
    if payload.registration_enabled is not None:
        settings.registration_enabled = payload.registration_enabled
    if payload.runner_concurrency is not None:
        settings.runner_concurrency = payload.runner_concurrency
    settings.updated_by = admin.id
    settings.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(settings)
    return settings


@router.get("/monitor", response_model=ServerMonitor)
def server_monitor(
    session: Session = Depends(get_session),
    _: UserAccount = Depends(admin_user),
) -> ServerMonitor:
    now = datetime.now(UTC)
    heartbeat = session.get(RunnerHeartbeat, "default")
    telemetry = session.get(ServiceTelemetry, "runner")
    runner_recent = bool(heartbeat and aware(heartbeat.updated_at) >= now - timedelta(seconds=15))
    database_started = time.perf_counter()
    session.execute(text("SELECT 1"))
    database_latency_ms = round((time.perf_counter() - database_started) * 1_000, 2)
    queue_counts = {item.value: count(session, BenchmarkRun.id, BenchmarkRun.status == item) for item in RunStatus}
    return ServerMonitor(
        observed_at=now,
        api=api_metrics(),
        runner={
            "healthy": runner_recent,
            "docker_ready": bool(heartbeat and heartbeat.docker_ready),
            "detail": heartbeat.detail if heartbeat else "No Runner heartbeat",
            "last_heartbeat": heartbeat.updated_at.isoformat() if heartbeat else None,
            "telemetry_fresh": bool(telemetry and aware(telemetry.observed_at) >= now - timedelta(seconds=20)),
            **(telemetry.metrics if telemetry else {}),
        },
        database={
            "healthy": True,
            "dialect": session.bind.dialect.name if session.bind else "unknown",
            "latency_ms": database_latency_ms,
        },
        queue={
            "counts": queue_counts,
            "active": sum(
                queue_counts[item.value] for item in (RunStatus.preparing, RunStatus.running, RunStatus.scoring)
            ),
            "queued": queue_counts[RunStatus.queued.value],
        },
    )


def count(session: Session, column, *criteria) -> int:
    return session.scalar(select(func.count(column)).where(*criteria)) or 0


def revoke_user_sessions(
    session: Session,
    user_id: uuid.UUID,
    *,
    preserve: uuid.UUID | None = None,
) -> None:
    statement = select(UserSession).where(UserSession.user_id == user_id)
    if preserve is not None:
        statement = statement.where(UserSession.id != preserve)
    for item in session.scalars(statement).all():
        session.delete(item)


def api_metrics() -> dict:
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    memory = memory_metrics()
    artifact_root = Path(get_settings().artifact_root)
    disk_target = artifact_root if artifact_root.exists() else Path("/")
    disk = shutil.disk_usage(disk_target)
    return {
        "healthy": True,
        "cpu_count": os.cpu_count() or 1,
        "load_1": round(load[0], 2),
        "load_5": round(load[1], 2),
        "load_15": round(load[2], 2),
        **memory,
        "disk_total": disk.total,
        "disk_used": disk.used,
        "disk_available": disk.free,
        "uptime_seconds": uptime_seconds(),
    }


def memory_metrics() -> dict:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, raw = line.partition(":")
            if key in {"MemTotal", "MemAvailable"}:
                values[key] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError):
        pass
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    return {
        "memory_total": total,
        "memory_available": available,
        "memory_used": max(0, total - available),
    }


def uptime_seconds() -> float | None:
    try:
        return round(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]), 1)
    except (OSError, ValueError, IndexError):
        return None
