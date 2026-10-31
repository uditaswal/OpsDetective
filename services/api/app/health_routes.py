import asyncio
from collections.abc import AsyncIterator
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.db import get_db, get_session_factory
from app.health import HealthOverview, ServiceHealth, snapshot
from app.models import Admin, LoginSession, Project, Service
from app.schemas import ServiceOut
from app.scope import scoped_select
from app.security import current_session, digest

router = APIRouter(prefix="/api/v1")
stream_lock = Lock()
active_streams: dict[str, set[str]] = {}
STREAM_INTERVAL_SECONDS = 5
STREAM_SNAPSHOTS = 60


def project_services(db: Session, tenant_id: str, project_id: str) -> list[ServiceOut]:
    project = db.scalar(scoped_select(Project, tenant_id).where(Project.id == project_id))
    if project is None:
        raise HTTPException(404, "Project not found")
    rows = db.scalars(scoped_select(Service, tenant_id, project_id)
                      .order_by(Service.created_at.desc(), Service.id).limit(100))
    return [ServiceOut.model_validate(row) for row in rows]


@router.get("/projects/{project_id}/health", response_model=HealthOverview)
def project_health(project_id: str, auth: tuple[Admin, LoginSession] = Depends(current_session),
                   db: Session = Depends(get_db)) -> HealthOverview:
    tenant_id = auth[0].tenant_id
    services = project_services(db, tenant_id, project_id)
    db.rollback()
    return snapshot(tenant_id, project_id, services)


@router.get("/services/{service_id}/health", response_model=ServiceHealth)
def service_health(service_id: str, auth: tuple[Admin, LoginSession] = Depends(current_session),
                   db: Session = Depends(get_db)) -> ServiceHealth:
    tenant_id = auth[0].tenant_id
    service = db.scalar(scoped_select(Service, tenant_id).where(Service.id == service_id))
    if service is None:
        raise HTTPException(404, "Service not found")
    ref = ServiceOut.model_validate(service)
    db.rollback()
    return snapshot(tenant_id, ref.project_id, [ref]).services[0]


def reserve_stream(session_key: str) -> str:
    with stream_lock:
        if len(active_streams.get(session_key, set())) >= 2 or sum(map(len, active_streams.values())) >= 16:
            raise HTTPException(429, "Live update limit reached; use polling")
        lease = uuid4().hex
        active_streams.setdefault(session_key, set()).add(lease)
    return lease


def release_stream(session_key: str, lease: str) -> None:
    with stream_lock:
        leases = active_streams.get(session_key, set())
        leases.discard(lease)
        if not leases:
            active_streams.pop(session_key, None)


def stream_snapshot(factory: sessionmaker, token: str, project_id: str) -> HealthOverview:
    with factory() as db:
        admin, _ = current_session(db=db, session_token=token)
        tenant_id = admin.tenant_id
        services = project_services(db, tenant_id, project_id)
    return snapshot(tenant_id, project_id, services)


async def health_events(request: Request, factory: sessionmaker, token: str, project_id: str,
                        session_key: str, lease: str) -> AsyncIterator[str]:
    try:
        yield "retry: 3000\n\n"
        for index in range(STREAM_SNAPSHOTS):
            if await request.is_disconnected():
                return
            try:
                overview = await run_in_threadpool(stream_snapshot, factory, token, project_id)
            except HTTPException:
                yield 'event: access-lost\ndata: {}\n\n'
                return
            yield f"event: health\ndata: {overview.model_dump_json()}\n\n"
            if index + 1 < STREAM_SNAPSHOTS:
                await asyncio.sleep(STREAM_INTERVAL_SECONDS)
    finally:
        release_stream(session_key, lease)


@router.get("/projects/{project_id}/health/stream")
def health_stream(project_id: str, request: Request, session_token: str = Cookie(default=""),
                  auth: tuple[Admin, LoginSession] = Depends(current_session),
                  db: Session = Depends(get_db), factory: sessionmaker = Depends(get_session_factory)) -> StreamingResponse:
    project_services(db, auth[0].tenant_id, project_id)
    db.rollback()
    session_key = digest(session_token)
    lease = reserve_stream(session_key)
    return StreamingResponse(health_events(request, factory, session_token, project_id, session_key, lease),
                             media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})
