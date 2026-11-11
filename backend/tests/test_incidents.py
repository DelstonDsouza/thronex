from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import SessionLocal
from app.models import OrganizationMember, Role
from app.services import detection


def ml_anomaly(
    metric="latency_p95", observed=0.97, baseline=0.1, severity="high", ongoing=True
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "anomaly_id": "test-id",
        "metric_name": metric,
        "observed_value": observed,
        "baseline_value": baseline,
        "anomaly_score": 0.05,
        "severity": severity,
        "detected_at": now.isoformat(),
        "started_at": (now - timedelta(minutes=2)).isoformat(),
        "ended_at": now.isoformat(),
        "ongoing": ongoing,
        "model_version": "if-test",
        "explanation": "Evidence: test.",
        "contributing_signals": [
            {"metric": metric, "observed": observed, "baseline": baseline, "z_score": 16.0}
        ],
    }


@pytest.fixture
def s(client, make_user, monkeypatch):
    """A user with gateway -> order -> payment in Staging, and a fake ML service."""
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
    services = {}
    for name in ("api-gateway", "order-service", "payment-service"):
        services[name] = client.post(
            f"/environments/{env['id']}/services", json={"name": name}, headers=h
        ).json()
    for a, b in (("api-gateway", "order-service"), ("order-service", "payment-service")):
        r = client.post(
            f"/environments/{env['id']}/dependencies",
            json={"source_service_id": services[a]["id"], "target_service_id": services[b]["id"]},
            headers=h,
        )
        assert r.status_code == 201, r.text

    ml: dict = {}  # service name -> list of anomalies, or None for "no trained model"

    def fake_call_ml(service, environment, application):
        result = ml.get(service, [])
        return (None, "no trained model") if result is None else (result, "ok")

    monkeypatch.setattr(detection, "call_ml", fake_call_ml)

    def run():
        r = client.post(f"/environments/{env['id']}/detection/run", headers=h)
        assert r.status_code == 200, r.text
        return r.json()

    def incidents():
        return client.get(f"/organizations/{user['org_id']}/incidents", headers=h).json()

    def detail(incident_id):
        return client.get(f"/incidents/{incident_id}", headers=h).json()

    return {
        "user": user, "h": h, "env": env, "services": services,
        "ml": ml, "run": run, "incidents": incidents, "detail": detail,
    }


def test_repeated_detection_creates_one_incident_and_one_anomaly(s):
    s["ml"]["payment-service"] = [ml_anomaly()]
    for _ in range(3):
        s["run"]()
    incidents = s["incidents"]()
    assert len(incidents) == 1
    assert incidents[0]["status"] == "detected"
    assert incidents[0]["category"] == "high_latency"
    assert len(s["detail"](incidents[0]["id"])["anomalies"]) == 1


def test_connected_services_share_one_incident_with_origin_hypothesis(s):
    s["ml"]["payment-service"] = [ml_anomaly()]
    s["run"]()
    s["ml"]["order-service"] = [ml_anomaly(metric="error_rate", observed=0.33, baseline=0.0)]
    s["ml"]["api-gateway"] = [ml_anomaly(metric="error_rate", observed=0.33, baseline=0.0)]
    s["run"]()

    incidents = s["incidents"]()
    assert len(incidents) == 1
    d = s["detail"](incidents[0]["id"])
    assert len(d["anomalies"]) == 3
    assert d["service_id"] == s["services"]["payment-service"]["id"]
    assert "may originate in payment-service" in d["root_cause_hypothesis"]
    assert "not proof" in d["root_cause_hypothesis"]
    assert sum(e["event_type"] == "anomaly_added" for e in d["events"]) == 3


def test_unconnected_service_gets_its_own_incident(client, s):
    audit = client.post(
        f"/environments/{s['env']['id']}/services", json={"name": "audit-service"}, headers=s["h"]
    )
    assert audit.status_code == 201
    s["ml"]["payment-service"] = [ml_anomaly()]
    s["ml"]["audit-service"] = [ml_anomaly()]
    s["run"]()
    assert len(s["incidents"]()) == 2


def test_recovery_is_recorded_once_and_incident_stays_open(s):
    s["ml"]["payment-service"] = [ml_anomaly()]
    s["run"]()
    s["ml"]["payment-service"] = []
    s["run"]()
    s["run"]()
    inc = s["incidents"]()[0]
    d = s["detail"](inc["id"])
    assert d["anomalies"][0]["ongoing"] is False
    assert [e["event_type"] for e in d["events"]].count("telemetry_recovered") == 1
    assert inc["status"] == "detected"


def test_severity_escalates_and_is_recorded(s):
    s["ml"]["payment-service"] = [ml_anomaly(severity="medium")]
    s["run"]()
    s["ml"]["payment-service"] = [ml_anomaly(severity="critical")]
    s["run"]()
    inc = s["incidents"]()[0]
    assert inc["severity"] == "critical"
    d = s["detail"](inc["id"])
    assert any(e["event_type"] == "severity_changed" for e in d["events"])


def test_cpu_anomaly_is_classified_as_resource_exhaustion(s):
    s["ml"]["payment-service"] = [ml_anomaly(metric="cpu_cores", observed=0.9, baseline=0.05)]
    s["run"]()
    assert s["incidents"]()[0]["category"] == "resource_exhaustion"


def test_service_without_model_is_skipped(s):
    s["ml"]["payment-service"] = None
    report = s["run"]()
    outcomes = {r["service"]: r["outcome"] for r in report["results"]}
    assert outcomes["payment-service"] == "skipped"
    assert s["incidents"]() == []


def test_lifecycle_rules_and_timestamps(client, s):
    s["ml"]["payment-service"] = [ml_anomaly()]
    s["run"]()
    iid = s["incidents"]()[0]["id"]
    h = s["h"]

    def move(status, notes=None):
        return client.post(f"/incidents/{iid}/status", json={"status": status, "resolution_notes": notes}, headers=h)

    assert move("mitigating").status_code == 409  # cannot skip straight to mitigating
    ack = move("acknowledged")
    assert ack.status_code == 200 and ack.json()["acknowledged_at"] is not None
    assert move("resolved").status_code == 400  # notes required
    done = move("resolved", "Restarted payment-service")
    assert done.status_code == 200 and done.json()["resolved_at"] is not None
    reopened = move("investigating")
    assert reopened.status_code == 200 and reopened.json()["resolved_at"] is None
    assert move("resolved", "Fixed config").status_code == 200
    assert move("closed").status_code == 200
    assert move("investigating").status_code == 409  # closed is final


def test_assign_and_comment(client, s, make_user):
    s["ml"]["payment-service"] = [ml_anomaly()]
    s["run"]()
    iid = s["incidents"]()[0]["id"]
    h = s["h"]

    ok = client.post(f"/incidents/{iid}/assign", json={"user_id": s["user"]["id"]}, headers=h)
    assert ok.status_code == 200 and ok.json()["assigned_user_id"] == s["user"]["id"]

    outsider = make_user()
    bad = client.post(f"/incidents/{iid}/assign", json={"user_id": outsider["id"]}, headers=h)
    assert bad.status_code == 400

    c = client.post(f"/incidents/{iid}/comments", json={"body": "Looking into it"}, headers=h)
    assert c.status_code == 201
    d = c.json()
    assert d["comments"][0]["body"] == "Looking into it"
    assert any(e["event_type"] == "comment" for e in d["events"])


def test_viewer_can_read_but_not_change_incident(client, s, make_user):
    s["ml"]["payment-service"] = [ml_anomaly()]
    s["run"]()
    iid = s["incidents"]()[0]["id"]
    viewer = make_user()
    with SessionLocal() as db:
        db.add(OrganizationMember(user_id=viewer["id"], organization_id=s["user"]["org_id"], role=Role.VIEWER))
        db.commit()
    assert client.get(f"/incidents/{iid}", headers=viewer["headers"]).status_code == 200
    r = client.post(f"/incidents/{iid}/status", json={"status": "acknowledged"}, headers=viewer["headers"])
    assert r.status_code == 403


def test_other_org_cannot_see_incidents(client, s, make_user):
    s["ml"]["payment-service"] = [ml_anomaly()]
    s["run"]()
    iid = s["incidents"]()[0]["id"]
    outsider = make_user()
    assert client.get(f"/incidents/{iid}", headers=outsider["headers"]).status_code == 404
    assert (
        client.get(f"/organizations/{s['user']['org_id']}/incidents", headers=outsider["headers"]).status_code
        == 404
    )


def test_stats_report_mttd_and_mttr(client, s):
    s["ml"]["payment-service"] = [ml_anomaly()]
    s["run"]()
    iid = s["incidents"]()[0]["id"]
    client.post(f"/incidents/{iid}/status", json={"status": "resolved", "resolution_notes": "done"}, headers=s["h"])
    r = client.get(f"/organizations/{s['user']['org_id']}/incidents/stats", headers=s["h"])
    assert r.status_code == 200
    stats = r.json()
    assert stats["total"] == 1 and stats["open"] == 0
    assert stats["mttr_seconds"] is not None and stats["mttr_seconds"] >= 0
    assert 100 <= stats["mttd_seconds"] <= 200  # the fake anomaly started 2 minutes earlier


def test_dependency_validation(client, s):
    h, env_id, svc = s["h"], s["env"]["id"], s["services"]
    pay, order = svc["payment-service"]["id"], svc["order-service"]["id"]

    same = client.post(f"/environments/{env_id}/dependencies", json={"source_service_id": pay, "target_service_id": pay}, headers=h)
    assert same.status_code == 400
    dup = client.post(f"/environments/{env_id}/dependencies", json={"source_service_id": order, "target_service_id": pay}, headers=h)
    assert dup.status_code == 409

    app_id = s["env"]["application_id"]
    other_env = client.post(f"/applications/{app_id}/environments", json={"name": "Dev", "env_type": "development"}, headers=h).json()
    foreign = client.post(f"/environments/{other_env['id']}/services", json={"name": "x"}, headers=h).json()
    cross = client.post(f"/environments/{env_id}/dependencies", json={"source_service_id": pay, "target_service_id": foreign["id"]}, headers=h)
    assert cross.status_code == 400