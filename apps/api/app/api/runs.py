import json
import time
import uuid
from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_session
from app.events import append_event
from app.investigation import graph_payload
from app.models import BenchmarkRun, ModelProfile, RunEvent, RunStatus, TaskDefinition
from app.schemas import EventRead, InvestigationGraph, RunCreate, RunRead

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunRead])
def list_runs(session: Session = Depends(get_session)) -> list[BenchmarkRun]:
    return list(session.scalars(select(BenchmarkRun).order_by(BenchmarkRun.created_at.desc()).limit(200)).all())


@router.post("", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
def create_run(payload: RunCreate, session: Session = Depends(get_session)) -> BenchmarkRun:
    task = session.get(TaskDefinition, payload.task_id)
    candidate = session.get(ModelProfile, payload.candidate_model_id)
    judge = session.get(ModelProfile, payload.judge_model_id) if payload.judge_model_id else None
    if not task or not candidate:
        raise HTTPException(status_code=400, detail="Unknown task or candidate model")
    if payload.judge_model_id == payload.candidate_model_id:
        raise HTTPException(status_code=400, detail="Candidate model cannot judge itself")
    if payload.judge_model_id and not judge:
        raise HTTPException(status_code=400, detail="Unknown judge model")
    run = BenchmarkRun(
        task_id=task.id,
        candidate_model_id=candidate.id,
        judge_model_id=judge.id if judge else None,
        config=payload.model_dump(mode="json", exclude={"task_id", "candidate_model_id", "judge_model_id"}),
    )
    session.add(run)
    session.flush()
    append_event(
        session,
        run.id,
        "run.queued",
        {"task": task.slug, "candidate": candidate.name, "judge": judge.name if judge else None},
    )
    session.commit()
    session.refresh(run)
    return run


@router.get("/{run_id}", response_model=RunRead)
def get_run(run_id: uuid.UUID, session: Session = Depends(get_session)) -> BenchmarkRun:
    run = session.get(BenchmarkRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/{run_id}/events", response_model=list[EventRead])
def get_events(
    run_id: uuid.UUID,
    after: int = 0,
    session: Session = Depends(get_session),
) -> list[RunEvent]:
    if not session.get(BenchmarkRun, run_id):
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
) -> dict:
    if not session.get(BenchmarkRun, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return graph_payload(session, run_id)


@router.get("/{run_id}/stream")
def stream_events(run_id: uuid.UUID) -> StreamingResponse:
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


@router.post("/{run_id}/cancel", response_model=RunRead)
def cancel_run(run_id: uuid.UUID, session: Session = Depends(get_session)) -> BenchmarkRun:
    run = session.get(BenchmarkRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in {RunStatus.completed, RunStatus.failed, RunStatus.cancelled}:
        return run
    run.status = RunStatus.cancelled
    run.stage = "Cancelled by user"
    append_event(session, run.id, "run.cancelled", {"reason": "user"})
    session.commit()
    session.refresh(run)
    return run


def active_run_count(session: Session) -> int:
    return (
        session.scalar(
            select(func.count(BenchmarkRun.id)).where(
                BenchmarkRun.status.in_([RunStatus.queued, RunStatus.preparing, RunStatus.running, RunStatus.scoring])
            )
        )
        or 0
    )
