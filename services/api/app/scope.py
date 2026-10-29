"""Tenant and project data-access guard.

Every read of tenant-owned data goes through these helpers so a missing filter
fails loudly instead of leaking rows across tenants or projects.
"""

from sqlalchemy import Select, select


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
