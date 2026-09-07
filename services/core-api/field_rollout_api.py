"""Authenticated dry-run sessions; no publisher or actuator dependencies."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from oidc import require_role
import field_rollout

router = APIRouter(prefix='/api/v1/robots/{robot_slug}/rollout-drills')


class StartRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    permit_id: str = Field(min_length=1, max_length=128)


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(strict=True, ge=0)


def operator(actor=Depends(require_role('admin', 'operator'))):
    if not actor or not actor.get('sub') or actor.get('role') not in {'admin', 'operator'}:
        raise HTTPException(403, detail={'code': 'OPERATOR_REQUIRED'})
    return actor


def call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except field_rollout.RolloutError as error:
        code = str(error)
        status = 404 if code == 'SESSION_NOT_FOUND' else 403 if code in {'OPERATOR_REQUIRED', 'SESSION_OWNER_REQUIRED'} else 409
        raise HTTPException(status, detail={'code': code}) from error


@router.post('')
def start(robot_slug: str, req: StartRequest, actor=Depends(operator)):
    return call(field_rollout.start, robot_slug, req.permit_id, actor)


@router.get('/active')
def active(robot_slug: str, actor=Depends(operator)):
    return call(field_rollout.active, robot_slug, actor)


@router.get('/{session_id}')
def get(robot_slug: str, session_id: str, actor=Depends(operator)):
    return call(field_rollout.get, session_id, robot_slug, actor)


@router.post('/{session_id}/advance')
def advance(robot_slug: str, session_id: str, req: TransitionRequest, actor=Depends(operator)):
    return call(field_rollout.transition, session_id, robot_slug, actor, req.revision)


@router.post('/{session_id}/rollback')
def rollback(robot_slug: str, session_id: str, req: TransitionRequest, actor=Depends(operator)):
    return call(field_rollout.transition, session_id, robot_slug, actor, req.revision, rollback=True)
