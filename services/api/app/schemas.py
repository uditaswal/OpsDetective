from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[\w .-]+$")


class ServiceIn(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120, pattern=r"^[\w .-]+$")
    environment: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


class ProjectOut(BaseModel):
    id: str
    name: str
    model_config = ConfigDict(from_attributes=True)


class ServiceOut(BaseModel):
    id: str
    project_id: str
    name: str
    environment: str
    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    id: str
    service_id: str
    prefix: str
    created_at: datetime
    revoked_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class TokenCreated(TokenOut):
    token: str


class IngestVerifyIn(BaseModel):
    token: str = Field(min_length=1, max_length=256)


class IngestVerifyOut(BaseModel):
    tenant_id: str
    project_id: str
    service_id: str


class DemoFaultIn(BaseModel):
    mode: Literal["off", "http_500", "slow_db"]
    duration_seconds: int = Field(default=60, ge=5, le=120)
