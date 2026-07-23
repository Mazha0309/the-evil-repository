import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import RunEvent


def append_event(session: Session, run_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> RunEvent:
    last_sequence = session.scalar(select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run_id))
    event = RunEvent(
        run_id=run_id,
        sequence=(last_sequence or 0) + 1,
        kind=kind,
        payload=payload,
    )
    session.add(event)
    session.flush()
    return event
