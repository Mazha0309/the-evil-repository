import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import BenchmarkRun, UserAccount
from app.security import can_access_run, current_user

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
    payload = {
        "run_id": str(run.id),
        "status": run.status.value,
        "score": run.score,
        "scorecard": run.scorecard,
        "tool_calls": run.tool_calls,
        "resources": {
            "provider_requests": run.scorecard.get("resources", {}).get(
                "provider_requests"
            ),
            "tokens": {
                "input": run.input_tokens,
                "output": run.output_tokens,
                "total": run.input_tokens + run.output_tokens,
            },
            "budgets": {
                key: value
                for key, value in run.config.items()
                if key.startswith("soft_") or key.startswith("hard_")
            },
        },
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error": run.error,
    }
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="run-{run.id}.json"'},
    )
