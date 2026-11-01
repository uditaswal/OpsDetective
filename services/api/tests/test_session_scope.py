from app.models import Admin, LoginSession
from app.scope import scoped_select
from app.security import digest, hasher
import pytest


def test_session_tenant_is_stored_and_foreign_admin_binding_is_rejected(workspace):
    client, factory, projects, _ = workspace
    key = digest(client.cookies["session_token"])
    with factory() as db:
        session = db.scalar(scoped_select(LoginSession, "tenant-a").where(LoginSession.token_hash == key))
        assert session is not None
        assert db.scalar(scoped_select(LoginSession, "tenant-b").where(LoginSession.token_hash == key)) is None
        other = Admin(tenant_id="tenant-b", email="other@example.invalid", password_hash=hasher.hash("synthetic-password"))
        db.add(other)
        db.flush()
        session.admin_id = other.id
        db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get(f"/api/v1/projects/{projects[0]}/health").status_code == 401
    assert client.get(f"/api/v1/projects/{projects[1]}/host").status_code == 401
    assert client.post("/api/v1/projects", json={"name": "Denied"},
                       headers={"X-CSRF-Token": client.cookies["csrf_token"]}).status_code == 401


def test_all_owned_models_carry_tenant_and_telemetry_models_project():
    from app.db import Base
    for table in Base.metadata.tables.values():
        assert "tenant_id" in table.columns, f"Missing tenant ownership on {table.name}"
    for name in ("services", "ingestion_tokens", "monitored_hosts"):
        assert "project_id" in Base.metadata.tables[name].columns


def test_credential_lookup_cannot_be_used_for_owned_project_reads():
    from app.models import Project
    from app.scope import credential_select
    with pytest.raises(TypeError):
        credential_select(Project, "0" * 64)
    with pytest.raises(ValueError):
        credential_select(LoginSession, "not-a-digest")
