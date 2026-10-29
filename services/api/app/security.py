import hmac
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.config import settings
from app.models import Admin, LoginSession

hasher = PasswordHasher()


def digest(value: str) -> str:
    return hmac.new(settings.session_secret.encode(), value.encode(), "sha256").hexdigest()


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_session(db: Session, admin: Admin) -> tuple[str, str]:
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(LoginSession(
        token_hash=digest(token), admin_id=admin.id, csrf_hash=digest(csrf),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
    ))
    db.commit()
    return token, csrf


def current_session(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None),
) -> tuple[Admin, LoginSession]:
    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    row = db.get(LoginSession, digest(session_token))
    if row is None or row.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    admin = db.get(Admin, row.admin_id)
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    return admin, row


def require_csrf(
    auth: tuple[Admin, LoginSession] = Depends(current_session),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> Admin:
    if not csrf_token or not secrets.compare_digest(digest(csrf_token), auth[1].csrf_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid CSRF token")
    return auth[0]
