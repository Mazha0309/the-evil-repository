import uuid

import yaml
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import TaskDefinition, UserAccount
from app.schemas import TaskCreate, TaskRead
from app.security import admin_csrf, current_user

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskRead])
def list_tasks(
    session: Session = Depends(get_session),
    _: UserAccount = Depends(current_user),
) -> list[TaskDefinition]:
    return list(session.scalars(select(TaskDefinition).order_by(TaskDefinition.created_at.desc())).all())


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    session: Session = Depends(get_session),
    _: UserAccount = Depends(admin_csrf),
) -> TaskDefinition:
    task = TaskDefinition(**payload.model_dump())
    session.add(task)
    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Task slug/version already exists") from exc
    session.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskRead)
def get_task(
    task_id: uuid.UUID,
    session: Session = Depends(get_session),
    _: UserAccount = Depends(current_user),
) -> TaskDefinition:
    task = session.get(TaskDefinition, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/export")
def export_task(
    task_id: uuid.UUID,
    session: Session = Depends(get_session),
    _: UserAccount = Depends(current_user),
) -> Response:
    task = session.get(TaskDefinition, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    body = yaml.safe_dump(task.manifest, sort_keys=False, allow_unicode=True)
    return Response(
        body,
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{task.slug}-{task.version}.yaml"'},
    )
