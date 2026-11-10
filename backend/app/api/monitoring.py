import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.access import load_environment, load_service
from app.api.deps import CurrentUser, DbSession
from app.models import Environment, Role, Service, ServiceStatus
from app.schemas.monitoring import EnvironmentSummary, ServiceMetrics, ServiceSummary
from app.services import prometheus
from app.services.prometheus import PrometheusError, label_value

router = APIRouter(tags=["monitoring"])

# __SEL__ is replaced with a label matcher such as: service="x",environment="y"
_RATE = "rate(http_requests_total{__SEL__}[1m])"
_ERRORS = 'rate(http_requests_total{__SEL__,status=~"5.."}[1m])'
_BUCKETS = "rate(http_request_duration_seconds_bucket{__SEL__}[1m])"

SERVICE_METRICS = {
    "request_rate": f"sum({_RATE})",
    "error_rate": f"sum({_ERRORS}) / sum({_RATE})",
    "latency_p50": f"histogram_quantile(0.50, sum by (le) ({_BUCKETS}))",
    "latency_p95": f"histogram_quantile(0.95, sum by (le) ({_BUCKETS}))",
    "latency_p99": f"histogram_quantile(0.99, sum by (le) ({_BUCKETS}))",
    "cpu_cores": "sum(rate(process_cpu_seconds_total{__SEL__}[1m]))",
    "memory_bytes": "sum(process_resident_memory_bytes{__SEL__})",
    "requests_in_progress": "sum(http_requests_in_progress{__SEL__})",
}

# One query per metric for the whole environment, grouped by service.
ENVIRONMENT_QUERIES = {
    "up": "max by (service) (up{__SEL__})",
    "request_rate": f"sum by (service) ({_RATE})",
    "error_rate": f"sum by (service) ({_ERRORS}) / sum by (service) ({_RATE})",
    "p95": f"histogram_quantile(0.95, sum by (service, le) ({_BUCKETS}))",
}

DEGRADED_ERROR_RATE = 0.05
UNHEALTHY_ERROR_RATE = 0.5
DEGRADED_P95_SECONDS = 1.0


def compute_status(
    up: float | None, error_rate: float | None, p95: float | None
) -> ServiceStatus:
    """Transparent health rules. Later, ML and incidents build on top of these."""
    if up is None:
        return ServiceStatus.UNKNOWN  # Prometheus has no data for this service
    if up < 1:
        return ServiceStatus.UNHEALTHY  # the scrape target is down
    if error_rate is not None and error_rate >= UNHEALTHY_ERROR_RATE:
        return ServiceStatus.UNHEALTHY
    if error_rate is not None and error_rate >= DEGRADED_ERROR_RATE:
        return ServiceStatus.DEGRADED
    if p95 is not None and p95 > DEGRADED_P95_SECONDS:
        return ServiceStatus.DEGRADED
    return ServiceStatus.HEALTHY


def _service_selector(service: Service) -> str:
    env_type = service.environment.env_type.value
    return f'service="{label_value(service.name)}",environment="{label_value(env_type)}"'


def _build_summary(env: Environment, services: list[Service]) -> list[ServiceSummary]:
    selector = f'environment="{label_value(env.env_type.value)}"'
    values: dict[str, dict[str, float | None]] = {}
    try:
        for key, template in ENVIRONMENT_QUERIES.items():
            result = prometheus.query_instant(template.replace("__SEL__", selector))
            values[key] = {
                item["labels"].get("service", ""): item["value"] for item in result
            }
    except PrometheusError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Prometheus unavailable: {exc}"
        )

    summaries = []
    for svc in services:
        up = values["up"].get(svc.name)
        error_rate = values["error_rate"].get(svc.name)
        p95 = values["p95"].get(svc.name)
        summaries.append(
            ServiceSummary(
                service_id=svc.id,
                name=svc.name,
                is_active=svc.is_active,
                up=None if up is None else up >= 1,
                request_rate=values["request_rate"].get(svc.name),
                error_rate=error_rate,
                p95_latency_seconds=p95,
                computed_status=compute_status(up, error_rate, p95),
                stored_status=svc.status,
            )
        )
    return summaries


def _list_services(db: DbSession, env: Environment) -> list[Service]:
    return list(
        db.scalars(
            select(Service).where(Service.environment_id == env.id).order_by(Service.name)
        )
    )


@router.get("/services/{service_id}/metrics", response_model=ServiceMetrics)
def service_metrics(
    service_id: int,
    db: DbSession,
    user: CurrentUser,
    minutes: int = Query(15, ge=1, le=1440),
) -> ServiceMetrics:
    service = load_service(db, user, service_id, Role.VIEWER)
    selector = _service_selector(service)
    end = time.time()
    start = end - minutes * 60
    step = max(5, minutes * 60 // 120)  # at most ~120 points per chart

    series: dict[str, list] = {}
    try:
        for name, template in SERVICE_METRICS.items():
            result = prometheus.query_range(
                template.replace("__SEL__", selector), start, end, step
            )
            series[name] = result[0]["points"] if result else []
    except PrometheusError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Prometheus unavailable: {exc}"
        )

    return ServiceMetrics(
        service_id=service.id,
        service_name=service.name,
        environment=service.environment.env_type.value,
        minutes=minutes,
        step_seconds=step,
        series=series,
    )


@router.get(
    "/environments/{env_id}/monitoring/summary", response_model=EnvironmentSummary
)
def environment_summary(
    env_id: int, db: DbSession, user: CurrentUser
) -> EnvironmentSummary:
    env = load_environment(db, user, env_id, Role.VIEWER)
    return EnvironmentSummary(
        environment_id=env.id,
        environment=env.name,
        services=_build_summary(env, _list_services(db, env)),
    )


@router.post(
    "/environments/{env_id}/monitoring/refresh-status",
    response_model=EnvironmentSummary,
)
def refresh_status(env_id: int, db: DbSession, user: CurrentUser) -> EnvironmentSummary:
    """Saves the computed status of each active service into the database."""
    env = load_environment(db, user, env_id, Role.OPERATOR)
    services = _list_services(db, env)
    summaries = _build_summary(env, services)
    now = datetime.now(timezone.utc)
    for svc, summary in zip(services, summaries):
        if svc.is_active:
            svc.status = summary.computed_status
            svc.last_health_check_at = now
            summary.stored_status = svc.status
    db.commit()
    return EnvironmentSummary(
        environment_id=env.id, environment=env.name, services=summaries
    )