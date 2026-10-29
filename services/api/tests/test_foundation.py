from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Admin, AuditEvent, Project
from app.security import hasher


def test_login_csrf_tenant_scope_and_audit() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Admin(tenant_id="tenant-a", email="admin@example.invalid",
                     password_hash=hasher.hash("correct-password")))
        other_project = Project(tenant_id="tenant-b", name="Other tenant")
        db.add(other_project)
        db.commit()
        other_project_id = other_project.id

    def db_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    try:
        with TestClient(app) as client:
            unauthenticated = client.get("/api/v1/projects")
            assert unauthenticated.status_code == 401
            assert unauthenticated.headers["content-type"] == "application/problem+json"
            assert client.post("/api/v1/auth/login", json={"email": "admin@example.invalid", "password": "wrong"}).status_code == 401
            login = client.post("/api/v1/auth/login", json={"email": "admin@example.invalid", "password": "correct-password"})
            assert login.status_code == 200
            csrf = login.json()["csrf_token"]
            assert client.get("/api/v1/projects").json() == []
            assert client.post("/api/v1/projects", json={"name": "Demo"}).status_code == 403
            created = client.post("/api/v1/projects", json={"name": "Demo"}, headers={"X-CSRF-Token": csrf})
            assert created.status_code == 201
            assert client.post("/api/v1/projects", json={"name": "Demo"}, headers={"X-CSRF-Token": csrf}).status_code == 409
            assert [p["name"] for p in client.get("/api/v1/projects").json()] == ["Demo"]
            bad = client.post("/api/v1/services", json={"project_id": "invalid", "name": "Wrong", "environment": "dev"}, headers={"X-CSRF-Token": csrf})
            assert bad.status_code == 404
            cross_tenant = client.post("/api/v1/services", json={"project_id": other_project_id, "name": "Wrong", "environment": "dev"}, headers={"X-CSRF-Token": csrf})
            assert cross_tenant.status_code == 404
            service = client.post("/api/v1/services", json={"project_id": created.json()["id"], "name": "Demo API", "environment": "dev"}, headers={"X-CSRF-Token": csrf})
            assert service.status_code == 201
            assert len(client.get("/api/v1/services").json()) == 1
            assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
            assert client.get("/api/v1/projects").status_code == 401
        with Session(engine) as db:
            assert len(list(db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == "tenant-a")))) == 4
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
