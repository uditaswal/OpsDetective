from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Admin
from app.security import hasher


def main() -> None:
    if not settings.admin_password or not settings.session_secret:
        raise RuntimeError("ADMIN_PASSWORD and SESSION_SECRET are required")
    if "change-me" in settings.admin_password or "change-me" in settings.session_secret:
        raise RuntimeError("Replace placeholder credentials in .env")
    with SessionLocal() as db:
        admin = db.scalar(select(Admin).where(Admin.email == settings.admin_email))
        if admin is None:
            db.add(Admin(tenant_id=settings.tenant_id, email=settings.admin_email,
                         password_hash=hasher.hash(settings.admin_password)))
            db.commit()


if __name__ == "__main__":
    main()
