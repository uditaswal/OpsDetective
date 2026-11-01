from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.host_assignment import SOURCE_KEY
from app.host_health import HostHealth, host_snapshot
from app.models import Admin, LoginSession, MonitoredHost, Project
from app.scope import scoped_select
from app.security import current_session

router = APIRouter(prefix="/api/v1")


@router.get("/projects/{project_id}/host", response_model=HostHealth)
def project_host(project_id: str, auth: tuple[Admin, LoginSession] = Depends(current_session),
                 db: Session = Depends(get_db)) -> HostHealth:
    tenant_id = auth[0].tenant_id
    if db.scalar(scoped_select(Project, tenant_id).where(Project.id == project_id)) is None:
        raise HTTPException(404, "Project not found")
    host = db.scalar(scoped_select(MonitoredHost, tenant_id, project_id)
                     .where(MonitoredHost.source_key == SOURCE_KEY))
    host_id = host.id if host else None
    db.rollback()
    if host_id is None:
        return HostHealth(project_id=project_id, observed_at=datetime.now(timezone.utc),
                          stale_seconds=settings.health_stale_seconds)
    return host_snapshot(project_id, host_id)
