from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import EnvironmentType, ServiceStatus, ServiceType


# ---------- Applications ----------
class ApplicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class ApplicationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    name: str
    description: str | None
    created_at: datetime


# ---------- Environments ----------
class EnvironmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    env_type: EnvironmentType
    chaos_enabled: bool = False


class EnvironmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    env_type: EnvironmentType | None = None
    chaos_enabled: bool | None = None


class EnvironmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    name: str
    env_type: EnvironmentType
    chaos_enabled: bool
    created_at: datetime


# ---------- Services ----------
class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    service_type: ServiceType = ServiceType.API
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    health_check_path: str | None = Field(default=None, max_length=255, pattern=r"^/")


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    service_type: ServiceType | None = None
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    health_check_path: str | None = Field(default=None, max_length=255, pattern=r"^/")
    is_active: bool | None = None


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    name: str
    description: str | None
    service_type: ServiceType
    host: str | None
    port: int | None
    health_check_path: str | None
    status: ServiceStatus
    is_active: bool
    last_health_check_at: datetime | None
    created_at: datetime