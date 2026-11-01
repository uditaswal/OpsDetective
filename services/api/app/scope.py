"""Tenant and project data-access guard.

Every read of tenant-owned data goes through these helpers so a missing filter
fails loudly instead of leaking rows across tenants or projects.
"""

from sqlalchemy import Select, select

from app.models import Admin, IngestionToken, LoginSession


def scoped_select(model: type, tenant_id: str, project_id: str | None = None) -> Select:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if not hasattr(model, "tenant_id"):
        raise TypeError(f"{model.__name__} has no tenant_id column")
    stmt = select(model).where(model.tenant_id == tenant_id)
    if project_id is not None:
        if not hasattr(model, "project_id"):
            raise TypeError(f"{model.__name__} has no project_id column")
        stmt = stmt.where(model.project_id == project_id)
    return stmt


def credential_select(model: type, token_hash: str) -> Select:
    """Resolve one opaque credential before its tenant is known."""
    if model not in (LoginSession, IngestionToken):
        raise TypeError("Only authentication credentials support identity lookup")
    if len(token_hash) != 64 or any(char not in "0123456789abcdef" for char in token_hash):
        raise ValueError("A keyed credential digest is required")
    return select(model).where(model.token_hash == token_hash).limit(1)


def login_select(email: str) -> Select:
    """Resolve a unique login identity; callers must verify its password."""
    return select(Admin).where(Admin.email == email).limit(1)
