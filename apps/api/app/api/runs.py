import json
import time
import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.reports import export_report
from app.challenge.spec import BudgetSpec
from app.config import get_settings
from app.database import SessionLocal, get_session
from app.events import append_event
from app.investigation import graph_payload
from app.model_identity import model_snapshot, task_snapshot
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
    UserRunAccess,
)
from app.scenario.agent_graph import AgentGraph, derive_agent_graph
from app.schemas import (
    BudgetAdjustment,
    EventRead,
    InvestigationGraph,
    RunArtifactRead,
    RunCreate,
    RunRead,
)
from app.security import can_access_model, can_access_run, csrf_protection, current_user

router = APIRouter(prefix="/runs", tags=["runs"])
settings = get_settings()

_BUDGET_FIELDS = (
    "soft_seconds",
    "hard_seconds",
    "soft_tool_calls",
    "hard_tool_calls",
    "soft_provider_requests",
    "hard_provider_requests",
    "soft_total_tokens",
    "hard_total_tokens",
)

_OPTIONAL_BUDGET_FIELDS = frozenset(
    {
        "soft_provider_requests",
        "hard_provider_requests",
        "soft_total_tokens",
        "hard_total_tokens",
    }
)


@router.get("", response_model=list[RunRead])
def list_runs(
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> list[BenchmarkRun]:
    statement = select(BenchmarkRun).where(BenchmarkRun.archived_at.is_(None))
    if user.role != UserRole.admin:
        statement = statement.join(
            UserRunAccess,
            UserRunAccess.run_id == BenchmarkRun.id,
        ).where(UserRunAccess.user_id == user.id)
    return list(session.scalars(statement.order_by(BenchmarkRun.created_at.desc()).limit(200)).all())


@router.post("", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
def create_run(
    payload: RunCreate,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> BenchmarkRun:
    task = session.get(TaskDefinition, payload.task_id)
    model_ids = {payload.candidate_model_id}
    if payload.judge_model_id is not None:
        model_ids.add(payload.judge_model_id)
    locked_profiles = session.scalars(
        select(ModelProfile).where(ModelProfile.id.in_(model_ids)).order_by(ModelProfile.id).with_for_update()
    ).all()
    profiles = {profile.id: profile for profile in locked_profiles}
    candidate = profiles.get(payload.candidate_model_id)
    judge = profiles.get(payload.judge_model_id) if payload.judge_model_id else None
    if (
        not task
        or not task.enabled
        or not can_access_model(session, user, candidate)
        or not candidate.enabled
        or candidate.archived_at is not None
    ):
        raise HTTPException(status_code=400, detail="Unknown task or candidate model")
    if payload.judge_model_id == payload.candidate_model_id:
        raise HTTPException(status_code=400, detail="Candidate model cannot judge itself")
    if payload.judge_model_id and (
        not can_access_model(session, user, judge) or not judge.enabled or judge.archived_at is not None
    ):
        raise HTTPException(status_code=400, detail="Unknown judge model")
    if candidate.provider == ModelProvider.antigravity and payload.soft_total_tokens is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Antigravity CLI does not expose machine-readable token usage; "
                "use time, tool-call, and Provider-request budgets instead"
            ),
        )
    completion = task.manifest.get("completion", {})
    minimum_calls = int(completion.get("min_tool_calls", 0))
    if payload.hard_tool_calls < minimum_calls:
        raise HTTPException(
            status_code=400,
            detail=f"Hard tool-call budget must be at least {minimum_calls} for this Scenario",
        )
    run_config = payload.model_dump(
        mode="json",
        exclude={"task_id", "candidate_model_id", "judge_model_id"},
    )
    scenario_budget = task.manifest.get("budget", {})
    provider_fields = {"soft_provider_requests", "hard_provider_requests"}
    if not provider_fields.intersection(payload.model_fields_set):
        for field in provider_fields:
            run_config[field] = scenario_budget.get(field)
    run_config["candidate_model_snapshot"] = model_snapshot(candidate)
    run_config["task_snapshot"] = task_snapshot(task)
    if judge is not None:
        run_config["judge_model_snapshot"] = model_snapshot(judge)
    run = BenchmarkRun(
        task_id=task.id,
        candidate_model_id=candidate.id,
        judge_model_id=judge.id if judge else None,
        config=run_config,
    )
    session.add(run)
    session.flush()
    session.add(UserRunAccess(user_id=user.id, run_id=run.id))
    append_event(
        session,
        run.id,
        "run.queued",
        {"task": task.slug, "candidate": candidate.name, "judge": judge.name if judge else None},
    )
    session.commit()
    session.refresh(run)
    return run


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_run(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> None:
    run = session.scalar(select(BenchmarkRun).where(BenchmarkRun.id == run_id).with_for_update())
    if not can_access_run(session, user, run):
        raise HTTPException(status_code=404, detail="Run not found")
    assert run is not None
    if run.status not in {
        RunStatus.completed,
        RunStatus.failed,
        RunStatus.cancelled,
    }:
        raise HTTPException(
            status_code=409,
            detail="Active runs must finish or be cancelled before archival",
        )
    append_event(
        session,
        run.id,
        "run.archived",
        {"actor_user_id": str(user.id)},
    )
    run.archived_at = datetime.now(UTC)
    session.commit()


@router.get("/{run_id}", response_model=RunRead)
def get_run(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> BenchmarkRun:
    run = session.get(BenchmarkRun, run_id)
    if not can_access_run(session, user, run):
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/{run_id}/export")
def export_run_archive(
    run_id: uuid.UUID,
    format: str = "json",
    include: str = "all",
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> Response:
    run = session.get(BenchmarkRun, run_id)
    if not can_access_run(session, user, run):
        raise HTTPException(status_code=404, detail="Run not found")
    if format == "json":
        return export_report(
            run_id,
            include=("full-events" if include == "full-events" else "compact"),
            session=session,
            user=user,
        )
    if format == "html":
        archive_path = Path(get_settings().artifact_root) / f"{run_id}.tar.gz"
        if archive_path.exists():
            import tarfile as tarfile_module

            with tarfile_module.open(archive_path, "r:gz") as source:
                member = next(
                    (m for m in source.getmembers() if m.isfile() and m.name == "report.html"),
                    None,
                )
                if member is not None:
                    return Response(
                        source.extractfile(member).read(),
                        media_type="text/html; charset=utf-8",
                        headers={"Content-Disposition": f'inline; filename="run-{run_id}.html"'},
                    )
        from app.api.diffs import _archive_candidates, _read_members
        from app.api.reports import build_report_payload
        from app.report_html import render_report_html, report_payload_for_html

        payload = build_report_payload(run_id, session, include="compact")
        for candidate in _archive_candidates(run_id):
            if candidate.exists():
                text_by_repo = {entry["repo"]: entry for entry in _read_members(candidate)}
                break
        else:
            text_by_repo = {}
        for diff in payload.get("diffs") or []:
            entry = text_by_repo.get(diff["repo"])
            if entry:
                diff["diff_text"] = entry.get("diff_text", "")
                diff["status_text"] = entry.get("status_text", "")
        model = dict(run.config).get("candidate_model_snapshot") or {}
        html = render_report_html(report_payload_for_html(payload, model=model))
        return Response(
            html.encode("utf-8"),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="run-{run_id}.html"'},
        )
    if format != "tar.gz":
        raise HTTPException(status_code=400, detail="format must be json, tar.gz or html")
    archive_path = Path(get_settings().artifact_root) / f"{run_id}.tar.gz"
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail="No run archive available")
    if include == "all":
        return FileResponse(
            archive_path,
            media_type="application/gzip",
            filename=archive_path.name,
        )
    allowed = set(part.strip() for part in include.split(","))
    path_markers = {
        "events": ["events.jsonl"],
        "telemetry": ["telemetry/"],
        "diffs": ["artifacts/"],
        "graph": ["investigation/"],
    }
    keep = [marker for name, markers in path_markers.items() if name in allowed for marker in markers]
    if not keep:
        raise HTTPException(status_code=400, detail="No matching archive content")
    import io
    import tarfile as tarfile_module

    buffer = io.BytesIO()
    with (
        tarfile_module.open(archive_path, "r:gz") as source,
        tarfile_module.open(fileobj=buffer, mode="w:gz") as out,
    ):
        for member in source.getmembers():
            if member.isfile() and any(member.name.startswith(marker) for marker in keep):
                payload = source.extractfile(member)
                out.addfile(member, payload)
    buffer.seek(0)
    return Response(
        buffer.getvalue(),
        media_type="application/gzip",
        headers={"Content-Disposition": (f'attachment; filename="run-{run_id}-filtered.tar.gz"')},
    )


@router.get("/{run_id}/artifacts", response_model=list[RunArtifactRead])
def list_run_artifacts(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> list[RunArtifact]:
    if not can_access_run(session, user, session.get(BenchmarkRun, run_id)):
        raise HTTPException(status_code=404, detail="Run not found")
    return list(
        session.scalars(select(RunArtifact).where(RunArtifact.run_id == run_id).order_by(RunArtifact.created_at)).all()
    )


@router.get("/{run_id}/artifacts/{artifact_id}")
def download_run_artifact(
    run_id: uuid.UUID,
    artifact_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> FileResponse:
    if not can_access_run(session, user, session.get(BenchmarkRun, run_id)):
        raise HTTPException(status_code=404, detail="Run not found")
    artifact = session.scalar(
        select(RunArtifact).where(
            RunArtifact.id == artifact_id,
            RunArtifact.run_id == run_id,
        )
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact_root = Path(settings.artifact_root).resolve()
    artifact_path = Path(artifact.path).resolve()
    if artifact_path != artifact_root and artifact_root not in artifact_path.parents:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not artifact_path.is_file():
        raise HTTPException(status_code=410, detail="Artifact file is unavailable")
    return FileResponse(
        artifact_path,
        media_type=artifact.media_type,
        filename=artifact.name,
    )


@router.get("/{run_id}/events", response_model=list[EventRead])
def get_events(
    run_id: uuid.UUID,
    after: int = 0,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> list[RunEvent]:
    if not can_access_run(session, user, session.get(BenchmarkRun, run_id)):
        raise HTTPException(status_code=404, detail="Run not found")
    return list(
        session.scalars(
            select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.sequence > after).order_by(RunEvent.sequence)
        ).all()
    )


@router.get("/{run_id}/graph", response_model=InvestigationGraph)
def get_investigation_graph(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> dict:
    if not can_access_run(session, user, session.get(BenchmarkRun, run_id)):
        raise HTTPException(status_code=404, detail="Run not found")
    return graph_payload(session, run_id)


@router.get("/{run_id}/agents", response_model=AgentGraph)
def get_agent_graph(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> AgentGraph:
    if not can_access_run(session, user, session.get(BenchmarkRun, run_id)):
        raise HTTPException(status_code=404, detail="Run not found")
    events = session.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.sequence)).all()
    return derive_agent_graph([{"kind": event.kind, "sequence": event.sequence, **event.payload} for event in events])


@router.get("/{run_id}/stream")
def stream_events(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> StreamingResponse:
    if not can_access_run(session, user, session.get(BenchmarkRun, run_id)):
        raise HTTPException(status_code=404, detail="Run not found")

    def event_stream() -> Generator[str, None, None]:
        sequence = 0
        idle_ticks = 0
        while idle_ticks < 600:
            with SessionLocal() as session:
                run = session.get(BenchmarkRun, run_id)
                if not run:
                    yield 'event: error\ndata: {"detail":"Run not found"}\n\n'
                    return
                events = session.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.sequence > sequence)
                    .order_by(RunEvent.sequence)
                ).all()
                if events:
                    idle_ticks = 0
                    for event in events:
                        sequence = event.sequence
                        data = EventRead.model_validate(event).model_dump(mode="json")
                        yield f"event: {event.kind}\ndata: {json.dumps(data)}\n\n"
                else:
                    idle_ticks += 1
                    yield ": heartbeat\n\n"
                if run.status in {RunStatus.completed, RunStatus.failed, RunStatus.cancelled}:
                    return
            time.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{run_id}/budget", response_model=RunRead)
def adjust_run_budget(
    run_id: uuid.UUID,
    payload: BudgetAdjustment,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> BenchmarkRun:
    run = session.get(BenchmarkRun, run_id)
    if not can_access_run(session, user, run):
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in {RunStatus.queued, RunStatus.preparing, RunStatus.running}:
        raise HTTPException(
            status_code=409,
            detail="Budget can only be adjusted while the run is active",
        )
    candidate_snapshot = dict(run.config).get("candidate_model_snapshot", {})
    if candidate_snapshot.get("provider") == "antigravity" and (
        payload.soft_total_tokens is not None or payload.hard_total_tokens is not None
    ):
        raise HTTPException(
            status_code=400,
            detail="Antigravity CLI does not expose machine-readable token usage",
        )
    task = session.get(TaskDefinition, run.task_id)
    scenario_budget = dict(task.manifest.get("budget", {})) if task else {}
    current = dict(scenario_budget)
    current.update(dict(run.config))
    for override in list(dict(run.config).get("budget_overrides", [])):
        current[override["field"]] = override["value"]
    merged: dict[str, int | None] = {}
    for field in _BUDGET_FIELDS:
        payload_value = getattr(payload, field)
        if payload_value is not None:
            merged[field] = payload_value
        elif field in payload.model_fields_set and field in _OPTIONAL_BUDGET_FIELDS:
            merged[field] = None
        else:
            merged[field] = current.get(field)
    try:
        BudgetSpec(**merged)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    completion = task.manifest.get("completion", {}) if task else {}
    minimum_calls = int(completion.get("min_tool_calls", 0))
    if merged["hard_tool_calls"] is not None and merged["hard_tool_calls"] < minimum_calls:
        raise HTTPException(
            status_code=400,
            detail=f"Hard tool-call budget must be at least {minimum_calls} for this Scenario",
        )
    config = dict(run.config)
    config.setdefault("budget_overrides", [])
    overrides = list(config["budget_overrides"])
    requested_fields: list[str] = []
    for field in _BUDGET_FIELDS:
        value = getattr(payload, field)
        if value is None and (field not in _OPTIONAL_BUDGET_FIELDS or field not in payload.model_fields_set):
            continue
        requested_fields.append(field)
        overrides.append(
            {
                "field": field,
                "value": value,
                "reason": payload.reason,
                "requested_by": user.username,
                "requested_at": datetime.now(UTC).isoformat(),
            }
        )
    config["budget_overrides"] = overrides
    run.config = config
    append_event(
        session,
        run.id,
        "run.budget_adjustment_requested",
        {
            "reason": payload.reason,
            "fields": requested_fields,
        },
    )
    session.commit()
    session.refresh(run)
    return run


@router.post("/{run_id}/cancel", response_model=RunRead)
def cancel_run(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> BenchmarkRun:
    run = session.get(BenchmarkRun, run_id)
    if not can_access_run(session, user, run):
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in {RunStatus.completed, RunStatus.failed, RunStatus.cancelled}:
        return run
    config = dict(run.config)
    config["pause_requested"] = False
    run.config = config
    run.status = RunStatus.cancelled
    run.stage = "Cancelled by user"
    run.completed_at = datetime.now(UTC)
    append_event(session, run.id, "run.cancelled", {"reason": "user"})
    session.commit()
    session.refresh(run)
    return run


@router.post("/{run_id}/pause", response_model=RunRead)
def pause_run(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> BenchmarkRun:
    run = session.get(BenchmarkRun, run_id)
    if not can_access_run(session, user, run):
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != RunStatus.running:
        raise HTTPException(
            status_code=409,
            detail="Only an active candidate investigation can be paused",
        )
    config = dict(run.config)
    if config.get("pause_requested") is True:
        return run
    config["pause_requested"] = True
    run.config = config
    run.stage = "Pause requested"
    append_event(session, run.id, "run.pause_requested", {"reason": "user"})
    session.commit()
    session.refresh(run)
    return run


@router.post("/{run_id}/resume", response_model=RunRead)
def resume_run(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(csrf_protection),
) -> BenchmarkRun:
    run = session.get(BenchmarkRun, run_id)
    if not can_access_run(session, user, run):
        raise HTTPException(status_code=404, detail="Run not found")
    config = dict(run.config)
    if run.status != RunStatus.running or config.get("pause_requested") is not True:
        raise HTTPException(status_code=409, detail="Run is not paused")
    config["pause_requested"] = False
    run.config = config
    run.stage = "Resume requested"
    append_event(session, run.id, "run.resume_requested", {"reason": "user"})
    session.commit()
    session.refresh(run)
    return run


def active_run_count(session: Session) -> int:
    return (
        session.scalar(
            select(func.count(BenchmarkRun.id)).where(
                BenchmarkRun.status.in_([RunStatus.queued, RunStatus.preparing, RunStatus.running, RunStatus.scoring]),
                BenchmarkRun.archived_at.is_(None),
            )
        )
        or 0
    )
