import pytest

from app.api.monitoring import compute_status
from app.models import ServiceStatus
from app.services import prometheus
from app.services.prometheus import PrometheusError, label_value


# ---------- Pure logic ----------
def test_label_value_escapes_quotes_and_backslashes():
    assert label_value('a"b\\c') == 'a\\"b\\\\c'


@pytest.mark.parametrize(
    "up, error_rate, p95, expected",
    [
        (None, None, None, ServiceStatus.UNKNOWN),
        (0.0, None, None, ServiceStatus.UNHEALTHY),
        (1.0, 0.6, 0.1, ServiceStatus.UNHEALTHY),
        (1.0, 0.3, 0.1, ServiceStatus.DEGRADED),
        (1.0, 0.0, 2.5, ServiceStatus.DEGRADED),
        (1.0, None, None, ServiceStatus.HEALTHY),
        (1.0, 0.01, 0.2, ServiceStatus.HEALTHY),
    ],
)
def test_compute_status(up, error_rate, p95, expected):
    assert compute_status(up, error_rate, p95) == expected


# ---------- API with a fake Prometheus ----------
def _fake_instant(promql: str):
    if "status=~" in promql:
        value = 0.3
    elif "histogram_quantile" in promql:
        value = 0.2
    elif promql.startswith("max by (service) (up"):
        value = 1.0
    else:
        value = 10.0
    return [{"labels": {"service": "payment-service"}, "value": value}]


def _fake_range(promql: str, start: float, end: float, step: int):
    return [{"labels": {}, "points": [[start, 1.0], [end, 2.0]]}]


@pytest.fixture
def env_with_service(client, make_user):
    user = make_user()
    h = user["headers"]
    app = client.post(
        f"/organizations/{user['org_id']}/applications", json={"name": "Shop"}, headers=h
    ).json()
    env = client.post(
        f"/applications/{app['id']}/environments",
        json={"name": "Staging", "env_type": "staging"},
        headers=h,
    ).json()
    service = client.post(
        f"/environments/{env['id']}/services",
        json={"name": "payment-service"},
        headers=h,
    ).json()
    return {"user": user, "env": env, "service": service}


def test_summary_computes_status_from_prometheus(client, monkeypatch, env_with_service):
    monkeypatch.setattr(prometheus, "query_instant", _fake_instant)
    r = client.get(
        f"/environments/{env_with_service['env']['id']}/monitoring/summary",
        headers=env_with_service["user"]["headers"],
    )
    assert r.status_code == 200
    svc = r.json()["services"][0]
    assert svc["up"] is True
    assert svc["error_rate"] == 0.3
    assert svc["computed_status"] == "degraded"
    assert svc["stored_status"] == "unknown"  # summary never writes to the database


def test_refresh_status_persists_to_database(client, monkeypatch, env_with_service):
    monkeypatch.setattr(prometheus, "query_instant", _fake_instant)
    h = env_with_service["user"]["headers"]
    r = client.post(
        f"/environments/{env_with_service['env']['id']}/monitoring/refresh-status",
        headers=h,
    )
    assert r.status_code == 200
    stored = client.get(f"/services/{env_with_service['service']['id']}", headers=h).json()
    assert stored["status"] == "degraded"
    assert stored["last_health_check_at"] is not None


def test_service_metrics_returns_series(client, monkeypatch, env_with_service):
    monkeypatch.setattr(prometheus, "query_range", _fake_range)
    r = client.get(
        f"/services/{env_with_service['service']['id']}/metrics?minutes=10",
        headers=env_with_service["user"]["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert "request_rate" in body["series"] and "latency_p95" in body["series"]
    assert len(body["series"]["request_rate"]) == 2


def test_prometheus_down_returns_503(client, monkeypatch, env_with_service):
    def boom(promql: str):
        raise PrometheusError("connection refused")

    monkeypatch.setattr(prometheus, "query_instant", boom)
    r = client.get(
        f"/environments/{env_with_service['env']['id']}/monitoring/summary",
        headers=env_with_service["user"]["headers"],
    )
    assert r.status_code == 503


def test_other_org_cannot_read_metrics(client, make_user, monkeypatch, env_with_service):
    monkeypatch.setattr(prometheus, "query_range", _fake_range)
    outsider = make_user()
    r = client.get(
        f"/services/{env_with_service['service']['id']}/metrics",
        headers=outsider["headers"],
    )
    assert r.status_code == 404


def test_minutes_is_bounded(client, env_with_service):
    r = client.get(
        f"/services/{env_with_service['service']['id']}/metrics?minutes=999999",
        headers=env_with_service["user"]["headers"],
    )
    assert r.status_code == 422