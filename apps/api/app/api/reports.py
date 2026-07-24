import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.investigation import graph_payload
from app.models import (
    BenchmarkRun,
    RunArtifact,
    RunEvent,
    TaskDefinition,
    UserAccount,
)
from app.run_outcomes import normalize_scorecard_outcome
from app.schemas import InvestigationGraph
from app.security import can_access_run, current_user
from app.telemetry import (
    build_telemetry_bundle,
    sanitize_for_export,
    serialize_run_event,
)
from app.version import VERSION

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{run_id}")
def export_report(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: UserAccount = Depends(current_user),
) -> Response:
    run = session.get(BenchmarkRun, run_id)
    if not can_access_run(session, user, run):
        raise HTTPException(status_code=404, detail="Run not found")
    assert run is not None
    task = session.get(TaskDefinition, run.task_id)
    events = list(
        session.scalars(
            select(RunEvent)
            .where(RunEvent.run_id == run_id)
            .order_by(RunEvent.sequence)
        ).all()
    )
    artifacts = list(
        session.scalars(
            select(RunArtifact)
            .where(RunArtifact.run_id == run_id)
            .order_by(RunArtifact.created_at)
        ).all()
    )
    serialized_events = [serialize_run_event(event) for event in events]
    telemetry = build_telemetry_bundle(serialized_events)
    investigation = InvestigationGraph.model_validate(
        graph_payload(session, run_id)
    ).model_dump(mode="json")
    payload = {
        "export_schema_version": 2,
        "platform_version": VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "run": {
            "id": str(run.id),
            "task_id": str(run.task_id),
            "candidate_model_id": str(run.candidate_model_id),
            "judge_model_id": (
                str(run.judge_model_id) if run.judge_model_id else None
            ),
            "status": run.status.value,
            "stage": run.stage,
            "score": run.score,
            "tool_calls": run.tool_calls,
            "tokens": {
                "input": run.input_tokens,
                "output": run.output_tokens,
                "total": run.input_tokens + run.output_tokens,
            },
            "estimated_cost": run.estimated_cost,
            "config": sanitize_for_export(dict(run.config)),
            "created_at": run.created_at.isoformat(),
            "started_at": (
                run.started_at.isoformat() if run.started_at else None
            ),
            "completed_at": (
                run.completed_at.isoformat() if run.completed_at else None
            ),
            "error": run.error,
        },
        "scenario": (
            {
                "id": str(task.id),
                "slug": task.slug,
                "version": task.version,
                "name": task.name,
                "description": task.description,
                "category": task.category,
                "kind": task.kind,
                "manifest": sanitize_for_export(dict(task.manifest)),
            }
            if task
            else None
        ),
        "scorecard": normalize_scorecard_outcome(run.scorecard),
        "telemetry": {
            key: value
            for key, value in telemetry.items()
            if key != "events"
        },
        "investigation": investigation,
        "events": telemetry["events"],
        "artifacts": [
            {
                "id": str(artifact.id),
                "name": artifact.name,
                "media_type": artifact.media_type,
                "size": artifact.size,
                "sha256": artifact.sha256,
                "metadata": sanitize_for_export(artifact.metadata_json),
                "created_at": artifact.created_at.isoformat(),
            }
            for artifact in artifacts
        ],
        "privacy": {
            "credentials_included": False,
            "hidden_chain_of_thought_included": False,
            "visible_model_output_included": True,
            "tool_inputs_and_outputs_included": True,
            "redacted_key_classes": sorted(
                [
                    "authorization",
                    "api_key",
                    "access_token",
                    "refresh_token",
                    "id_token",
                    "password",
                    "secret",
                    "thought_signature",
                ]
            ),
        },
    }
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="run-{run.id}-telemetry.json"'
            )
        },
    )
