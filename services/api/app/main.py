import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock

import httpx
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Admin, AuditEvent, IngestionToken, LoginSession, Project, Service, utcnow
from app.schemas import DemoFaultIn, IngestVerifyIn, IngestVerifyOut, LoginIn, ProjectIn, ProjectOut, ServiceIn, ServiceOut, TokenCreated, TokenOut
from app.scope import scoped_select
from app.security import (create_session, current_session, digest, new_ingestion_token,
                          require_csrf, require_internal_key, verify_ingestion_token, verify_password)

app = FastAPI(title="OpsDetective API", version="0.1.0", docs_url=None, redoc_url=None)
attempts: dict[str, deque[datetime]] = defaultdict(deque)
demo_fault_attempts: dict[str, deque[float]] = defaultdict(deque)
demo_fault_attempts_lock = Lock()


@app.exception_handler(HTTPException)
async def http_problem(request: Request, exc: HTTPException) -> JSONResponse:
    title = {401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
             409: "Conflict", 429: "Too Many Requests"}.get(exc.status_code, "Request failed")
    return JSONResponse(status_code=exc.status_code, media_type="application/problem+json",
                        content={"type": "about:blank", "title": title,
                                 "status": exc.status_code, "detail": str(exc.detail)})


@app.exception_handler(RequestValidationError)
async def validation_problem(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [{"field": ".".join(str(part) for part in error["loc"]),
               "reason": error["type"]} for error in exc.errors()]
    return JSONResponse(status_code=422, media_type="application/problem+json",
                        content={"type": "about:blank", "title": "Validation failed",
                                 "status": 422, "detail": "Check the submitted fields", "fields": fields})


@app.middleware("http")
async def security_headers(request: Request, call_next):
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > 1_048_576:
                return JSONResponse(status_code=413, content={"detail": "Request too large"})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/auth/login")
def login(body: LoginIn, response: Response, request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    key = request.client.host if request.client else "unknown"
    now = datetime.now(timezone.utc)
    recent = attempts[key]
    while recent and recent[0] < now - timedelta(minutes=1):
        recent.popleft()
    if len(recent) >= 5:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Try again later")
    recent.append(now)
    admin = db.scalar(select(Admin).where(Admin.email == body.email))
    if admin is None or not verify_password(admin.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    recent.clear()
    token, csrf = create_session(db, admin)
    response.set_cookie("session_token", token, httponly=True, secure=settings.secure_cookies,
                        samesite="lax", max_age=8 * 3600, path="/")
    response.set_cookie("csrf_token", csrf, httponly=False, secure=settings.secure_cookies,
                        samesite="lax", max_age=8 * 3600, path="/")
    db.add(AuditEvent(tenant_id=admin.tenant_id, actor_id=admin.id,
                      action="auth.login", target_id=admin.id))
    db.commit()
    return {"csrf_token": csrf}


@app.get("/api/v1/auth/me")
def me(auth: tuple[Admin, LoginSession] = Depends(current_session)) -> dict[str, str]:
    return {"email": auth[0].email, "tenant_id": auth[0].tenant_id}


@app.post("/api/v1/auth/logout")
def logout(response: Response, admin: Admin = Depends(require_csrf),
           db: Session = Depends(get_db), session_token: str | None = Cookie(default=None)) -> dict[str, str]:
    if session_token:
        row = db.get(LoginSession, digest(session_token))
        if row is not None:
            db.delete(row)
    response.delete_cookie("session_token", path="/")
    response.delete_cookie("csrf_token", path="/")
    db.add(AuditEvent(tenant_id=admin.tenant_id, actor_id=admin.id,
                      action="auth.logout", target_id=admin.id))
    db.commit()
    return {"status": "signed_out"}


@app.get("/api/v1/projects", response_model=list[ProjectOut])
def list_projects(admin: tuple[Admin, LoginSession] = Depends(current_session),
                  db: Session = Depends(get_db)) -> list[Project]:
    return list(db.scalars(select(Project).where(Project.tenant_id == admin[0].tenant_id)
                           .order_by(Project.created_at.desc()).limit(100)))


@app.post("/api/v1/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, admin: Admin = Depends(require_csrf),
                   db: Session = Depends(get_db)) -> Project:
    project = Project(tenant_id=admin.tenant_id, name=body.name.strip())
    db.add(project)
    try:
        db.flush()
        db.add(AuditEvent(tenant_id=admin.tenant_id, actor_id=admin.id,
                          action="project.create", target_id=project.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Project already exists") from None
    return project


@app.get("/api/v1/services", response_model=list[ServiceOut])
def list_services(admin: tuple[Admin, LoginSession] = Depends(current_session),
                  db: Session = Depends(get_db)) -> list[Service]:
    return list(db.scalars(select(Service).where(Service.tenant_id == admin[0].tenant_id)
                           .order_by(Service.created_at.desc()).limit(100)))


@app.post("/api/v1/services", response_model=ServiceOut, status_code=201)
def create_service(body: ServiceIn, admin: Admin = Depends(require_csrf),
                   db: Session = Depends(get_db)) -> Service:
    project = db.scalar(select(Project).where(Project.id == body.project_id,
                                               Project.tenant_id == admin.tenant_id))
    if project is None:
        raise HTTPException(404, "Project not found")
    service = Service(tenant_id=admin.tenant_id, project_id=project.id,
                      name=body.name.strip(), environment=body.environment)
    db.add(service)
    try:
        db.flush()
        db.add(AuditEvent(tenant_id=admin.tenant_id, actor_id=admin.id,
                          action="service.create", target_id=service.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Service already exists") from None
    return service


def _owned_service(db: Session, admin: Admin, service_id: str) -> Service:
    service = db.scalar(scoped_select(Service, admin.tenant_id).where(Service.id == service_id))
    if service is None:
        raise HTTPException(404, "Service not found")
    return service


@app.post("/api/v1/services/{service_id}/tokens", response_model=TokenCreated, status_code=201)
def create_token(service_id: str, admin: Admin = Depends(require_csrf),
                 db: Session = Depends(get_db)) -> TokenCreated:
    service = _owned_service(db, admin, service_id)
    token = new_ingestion_token()
    row = IngestionToken(tenant_id=admin.tenant_id, project_id=service.project_id,
                         service_id=service.id, token_hash=digest(token), prefix=token[:8])
    db.add(row)
    db.flush()
    db.add(AuditEvent(tenant_id=admin.tenant_id, actor_id=admin.id,
                      action="token.create", target_id=row.id))
    db.commit()
    return TokenCreated(id=row.id, service_id=row.service_id, prefix=row.prefix,
                        created_at=row.created_at, revoked_at=None, token=token)


@app.get("/api/v1/services/{service_id}/tokens", response_model=list[TokenOut])
def list_tokens(service_id: str, auth: tuple[Admin, LoginSession] = Depends(current_session),
                db: Session = Depends(get_db)) -> list[IngestionToken]:
    service = _owned_service(db, auth[0], service_id)
    stmt = scoped_select(IngestionToken, auth[0].tenant_id, service.project_id)
    return list(db.scalars(stmt.where(IngestionToken.service_id == service.id)
                           .order_by(IngestionToken.created_at.desc()).limit(100)))


@app.delete("/api/v1/services/{service_id}/tokens/{token_id}", response_model=TokenOut)
def revoke_token(service_id: str, token_id: str, admin: Admin = Depends(require_csrf),
                 db: Session = Depends(get_db)) -> IngestionToken:
    service = _owned_service(db, admin, service_id)
    row = db.scalar(scoped_select(IngestionToken, admin.tenant_id, service.project_id)
                    .where(IngestionToken.id == token_id, IngestionToken.service_id == service.id))
    if row is None:
        raise HTTPException(404, "Token not found")
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        db.add(AuditEvent(tenant_id=admin.tenant_id, actor_id=admin.id,
                          action="token.revoke", target_id=row.id))
        db.commit()
    return row


@app.post("/internal/v1/ingest/verify", response_model=IngestVerifyOut,
          dependencies=[Depends(require_internal_key)])
def verify_ingest(body: IngestVerifyIn, db: Session = Depends(get_db)) -> IngestVerifyOut:
    row = verify_ingestion_token(db, body.token)
    if row is None:
        raise HTTPException(401, "Invalid or revoked token")
    return IngestVerifyOut(tenant_id=row.tenant_id, project_id=row.project_id, service_id=row.service_id)


@app.post("/api/v1/demo/faults", response_model=DemoFaultIn)
def set_demo_fault(body: DemoFaultIn, admin: Admin = Depends(require_csrf),
                   db: Session = Depends(get_db)) -> DemoFaultIn:
    """Enable a bounded synthetic fault after administrator and CSRF checks."""
    if not settings.demo_faults_enabled:
        raise HTTPException(404, "Not found")
    if not settings.demo_control_key:
        raise HTTPException(503, "Demo control is unavailable")
    now = time.monotonic()
    with demo_fault_attempts_lock:
        recent = demo_fault_attempts[admin.id]
        while recent and recent[0] <= now - 60:
            recent.popleft()
        if len(recent) >= 3:
            raise HTTPException(429, "Demo fault rate limit exceeded")
        recent.append(now)
    try:
        response = httpx.post("http://demo-app:8001/internal/faults", json=body.model_dump(),
                              headers={"X-Demo-Control-Key": settings.demo_control_key}, timeout=3)
    except httpx.HTTPError:
        raise HTTPException(503, "Demo service is unavailable") from None
    if response.status_code != 200:
        raise HTTPException(503, "Demo service rejected the fault")
    db.add(AuditEvent(tenant_id=admin.tenant_id, actor_id=admin.id,
                      action="demo.fault", target_id=admin.id))
    db.commit()
    return body
