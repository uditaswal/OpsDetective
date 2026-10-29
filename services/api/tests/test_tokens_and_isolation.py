from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Admin, AuditEvent, IngestionToken, Project, Service
from app.scope import scoped_select
from app.security import hasher, verify_ingestion_token

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture()
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Admin(tenant_id="tenant-a", email="admin@example.invalid",
                     password_hash=hasher.hash("correct-password")))
        other_project = Project(tenant_id="tenant-b", name="Other")
        db.add(other_project)
        db.flush()
        other_service = Service(tenant_id="tenant-b", project_id=other_project.id,
                                name="Foreign", environment="dev")
        db.add(other_service)
        db.commit()
        foreign_id = other_service.id

    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        csrf = client.post("/api/v1/auth/login", json={
            "email": "admin@example.invalid", "password": "correct-password"}).json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}
        project = client.post("/api/v1/projects", json={"name": "Demo"}, headers=headers).json()
        service = client.post("/api/v1/services", json={
            "project_id": project["id"], "name": "Demo API", "environment": "dev"}, headers=headers).json()
        yield client, engine, headers, service["id"], foreign_id
    app.dependency_overrides.clear()
    engine.dispose()


def test_token_shown_once_hashed_and_revocable(env) -> None:
    client, engine, headers, service_id, _ = env
    assert client.post(f"/api/v1/services/{service_id}/tokens").status_code == 403
    created = client.post(f"/api/v1/services/{service_id}/tokens", headers=headers)
    assert created.status_code == 201
    token = created.json()["token"]
    token_id = created.json()["id"]
    listed = client.get(f"/api/v1/services/{service_id}/tokens").json()
    assert [t["id"] for t in listed] == [token_id]
    assert "token" not in listed[0]
    with Session(engine) as db:
        stored = db.scalar(select(IngestionToken))
        assert token not in (stored.token_hash, stored.prefix)
        assert verify_ingestion_token(db, token) is not None
        assert verify_ingestion_token(db, "opd_wrong") is None
    revoked = client.delete(f"/api/v1/services/{service_id}/tokens/{token_id}", headers=headers)
    assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None
    with Session(engine) as db:
        assert verify_ingestion_token(db, token) is None
        actions = {e.action for e in db.scalars(select(AuditEvent))}
        assert {"token.create", "token.revoke"} <= actions


def test_tokens_are_tenant_scoped(env) -> None:
    client, engine, headers, service_id, foreign_id = env
    assert client.post(f"/api/v1/services/{foreign_id}/tokens", headers=headers).status_code == 404
    assert client.get(f"/api/v1/services/{foreign_id}/tokens").status_code == 404
    token_id = client.post(f"/api/v1/services/{service_id}/tokens", headers=headers).json()["id"]
    assert client.delete(f"/api/v1/services/{foreign_id}/tokens/{token_id}", headers=headers).status_code == 404


def test_scoped_select_requires_tenant_and_project_columns() -> None:
    with pytest.raises(ValueError):
        scoped_select(Project, "")
    with pytest.raises(TypeError):
        scoped_select(Project, "t", "p")


def test_cross_project_query_returns_nothing(env) -> None:
    client, engine, headers, service_id, _ = env
    client.post(f"/api/v1/services/{service_id}/tokens", headers=headers)
    with Session(engine) as db:
        service = db.get(Service, service_id)
        assert len(list(db.scalars(scoped_select(IngestionToken, "tenant-a", service.project_id)))) == 1
        assert list(db.scalars(scoped_select(IngestionToken, "tenant-a", "another-project"))) == []
        assert list(db.scalars(scoped_select(IngestionToken, "tenant-b"))) == []


def test_compose_has_no_local_llm_inference() -> None:
    compose = (REPO / "infra" / "docker-compose.yml").read_text().lower()
    for banned in ("ollama", "llama.cpp", "vllm", "text-generation-inference"):
        assert banned not in compose


def test_internal_verify_requires_key_and_rejects_revoked(env, monkeypatch) -> None:
    from app.config import settings
    client, engine, headers, service_id, _ = env
    token_resp = client.post(f"/api/v1/services/{service_id}/tokens", headers=headers).json()
    body = {"token": token_resp["token"]}
    monkeypatch.setattr(settings, "internal_api_key", "")
    assert client.post("/internal/v1/ingest/verify", json=body).status_code == 404
    monkeypatch.setattr(settings, "internal_api_key", "k" * 16)
    assert client.post("/internal/v1/ingest/verify", json=body).status_code == 403
    ok = client.post("/internal/v1/ingest/verify", json=body, headers={"X-Internal-Key": "k" * 16})
    assert ok.status_code == 200 and ok.json()["service_id"] == service_id
    client.delete(f"/api/v1/services/{service_id}/tokens/{token_resp['id']}", headers=headers)
    gone = client.post("/internal/v1/ingest/verify", json=body, headers={"X-Internal-Key": "k" * 16})
    assert gone.status_code == 401
