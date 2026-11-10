from pydantic import BaseModel

from app.models import ServiceStatus

Point = tuple[float, float | None]  # (unix timestamp, value or None if no data)


class ServiceMetrics(BaseModel):
    service_id: int
    service_name: str
    environment: str
    minutes: int
    step_seconds: int
    series: dict[str, list[Point]]


class ServiceSummary(BaseModel):
    service_id: int
    name: str
    is_active: bool
    up: bool | None
    request_rate: float | None
    error_rate: float | None
    p95_latency_seconds: float | None
    computed_status: ServiceStatus
    stored_status: ServiceStatus


class EnvironmentSummary(BaseModel):
    environment_id: int
    environment: str
    services: list[ServiceSummary]