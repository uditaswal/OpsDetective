from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
import pytest

from app import health_routes
from app.db import Base, get_db, get_session_factory
from app.main import app
from app.models import Admin, Project, Service
from app.security import hasher


@pytest.fixture()
def workspace():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    projects = []
    services = []
    with factory() as db:
        db.add(Admin(tenant_id="tenant-a", email="admin@example.invalid",
                     password_hash=hasher.hash("correct-password")))
        for index, tenant in enumerate(("tenant-a", "tenant-a", "tenant-b")):
            project = Project(tenant_id=tenant, name=f"Project {index}")
            db.add(project)
            db.flush()
            service = Service(tenant_id=tenant, project_id=project.id,
                              name=f"Service {index}", environment="test", probe_name="demo")
            db.add(service)
            db.flush()
            projects.append(project.id)
            services.append(service.id)
        db.commit()

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_session_factory] = lambda: factory
    try:
        with TestClient(app) as client:
            client.post("/api/v1/auth/login", json={"email": "admin@example.invalid",
                        "password": "correct-password"}).raise_for_status()
            yield client, factory, projects, services
    finally:
        app.dependency_overrides.clear()
        health_routes.active_streams.clear()
        engine.dispose()

