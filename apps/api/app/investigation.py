import hashlib
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.events import append_event
from app.models import (
    Evidence,
    EvidenceEdge,
    EvidenceRelation,
    Hypothesis,
    HypothesisRevision,
    HypothesisStatus,
)


def record_hypothesis(
    session: Session,
    run_id: uuid.UUID,
    *,
    key: str,
    statement: str,
    status: str,
    confidence: float,
    next_action: str | None,
    reason: str | None = None,
) -> Hypothesis:
    hypothesis = session.scalar(select(Hypothesis).where(Hypothesis.run_id == run_id, Hypothesis.key == key))
    parsed_status = HypothesisStatus(status)
    confidence = max(0, min(float(confidence), 1))
    if hypothesis is None:
        hypothesis = Hypothesis(
            run_id=run_id,
            key=key,
            statement=statement,
            status=parsed_status,
            confidence=confidence,
            next_action=next_action,
        )
        session.add(hypothesis)
        session.flush()
    else:
        hypothesis.statement = statement
        hypothesis.status = parsed_status
        hypothesis.confidence = confidence
        hypothesis.next_action = next_action
    sequence = session.scalar(
        select(func.max(HypothesisRevision.sequence)).where(HypothesisRevision.hypothesis_id == hypothesis.id)
    )
    session.add(
        HypothesisRevision(
            hypothesis_id=hypothesis.id,
            sequence=(sequence or 0) + 1,
            statement=statement,
            status=parsed_status,
            confidence=confidence,
            next_action=next_action,
            reason=reason,
        )
    )
    append_event(
        session,
        run_id,
        "investigation.hypothesis",
        {
            "key": key,
            "statement": statement,
            "status": parsed_status.value,
            "confidence": confidence,
            "next_action": next_action,
            "reason": reason,
        },
    )
    return hypothesis


def record_evidence(
    session: Session,
    run_id: uuid.UUID,
    *,
    key: str,
    source_type: str,
    source_ref: str,
    summary: str,
    trust: float,
) -> Evidence:
    existing = session.scalar(select(Evidence).where(Evidence.run_id == run_id, Evidence.key == key))
    if existing:
        raise ValueError(f"Evidence key already exists: {key}")
    item = Evidence(
        run_id=run_id,
        key=key,
        source_type=source_type,
        source_ref=source_ref,
        summary=summary,
        trust=max(0, min(float(trust), 1)),
        content_hash=hashlib.sha256(summary.encode()).hexdigest(),
    )
    session.add(item)
    append_event(
        session,
        run_id,
        "investigation.evidence",
        {
            "key": key,
            "source_type": source_type,
            "source_ref": source_ref,
            "summary": summary,
            "trust": item.trust,
        },
    )
    return item


def link_evidence(
    session: Session,
    run_id: uuid.UUID,
    *,
    source_type: str,
    source_key: str,
    target_type: str,
    target_key: str,
    relation: str,
    weight: float,
    explanation: str | None,
) -> EvidenceEdge:
    edge = EvidenceEdge(
        run_id=run_id,
        source_type=source_type,
        source_key=source_key,
        target_type=target_type,
        target_key=target_key,
        relation=EvidenceRelation(relation),
        weight=max(-1, min(float(weight), 1)),
        explanation=explanation,
    )
    session.add(edge)
    append_event(
        session,
        run_id,
        "investigation.edge",
        {
            "source_type": source_type,
            "source_key": source_key,
            "target_type": target_type,
            "target_key": target_key,
            "relation": edge.relation.value,
            "weight": edge.weight,
            "explanation": explanation,
        },
    )
    return edge


def graph_payload(session: Session, run_id: uuid.UUID) -> dict[str, list[Any]]:
    hypotheses = list(
        session.scalars(select(Hypothesis).where(Hypothesis.run_id == run_id).order_by(Hypothesis.created_at)).all()
    )
    hypothesis_ids = [item.id for item in hypotheses]
    revisions = (
        list(
            session.scalars(
                select(HypothesisRevision)
                .where(HypothesisRevision.hypothesis_id.in_(hypothesis_ids))
                .order_by(HypothesisRevision.created_at)
            ).all()
        )
        if hypothesis_ids
        else []
    )
    evidence = list(
        session.scalars(select(Evidence).where(Evidence.run_id == run_id).order_by(Evidence.created_at)).all()
    )
    edges = list(
        session.scalars(
            select(EvidenceEdge).where(EvidenceEdge.run_id == run_id).order_by(EvidenceEdge.created_at)
        ).all()
    )
    return {
        "hypotheses": hypotheses,
        "revisions": revisions,
        "evidence": evidence,
        "edges": edges,
    }
