"""Operator-only assignment of the deployment's fixed exporter."""

import argparse
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AuditEvent, MonitoredHost, Project
from app.scope import scoped_select

SOURCE_KEY = "monitoring-host"


def assign(db: Session, tenant_id: str, project_id: str) -> MonitoredHost:
    project = db.scalar(scoped_select(Project, tenant_id).where(Project.id == project_id))
    if project is None:
        raise ValueError("Project not found in that tenant")
    existing = db.scalar(scoped_select(MonitoredHost, tenant_id, project_id)
                         .where(MonitoredHost.source_key == SOURCE_KEY))
    if existing:
        return existing
    host = MonitoredHost(tenant_id=tenant_id, project_id=project_id, source_key=SOURCE_KEY)
    db.add(host)
    try:
        db.flush()
        db.add(AuditEvent(tenant_id=tenant_id, actor_id="operator", action="host.assign", target_id=host.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ValueError("Monitoring host is already assigned; unassign it before changing ownership") from None
    return host


def unassign(db: Session, tenant_id: str, project_id: str) -> None:
    host = db.scalar(scoped_select(MonitoredHost, tenant_id, project_id)
                     .where(MonitoredHost.source_key == SOURCE_KEY))
    if host is None:
        raise ValueError("Monitoring host assignment not found")
    db.add(AuditEvent(tenant_id=tenant_id, actor_id="operator", action="host.unassign", target_id=host.id))
    db.delete(host)
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Assign the fixed monitoring host to an owned project")
    parser.add_argument("action", choices=("assign", "unassign"))
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--project-id", required=True, type=UUID)
    args = parser.parse_args()
    if not 1 <= len(args.tenant_id) <= 64:
        parser.error("Tenant ID must contain 1–64 characters")
    try:
        with SessionLocal() as db:
            if args.action == "assign":
                assign(db, args.tenant_id, str(args.project_id))
            else:
                unassign(db, args.tenant_id, str(args.project_id))
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    print("Monitoring host assignment updated")


if __name__ == "__main__":
    main()
