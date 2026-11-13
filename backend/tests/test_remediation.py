from datetime import datetime, timezone

import pytest

from app.core.database import SessionLocal
from app.models import (
    Incident,
    IncidentCategory,
    IncidentStatus,
    OrganizationMember,
    Role,
    Severity,
)
from app.services import agent, prometheus
from app.services.agent import AgentError


@pytest.fixture
def r(client, make_user, monkeypatch):
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

    def make_service(name, host):
        body = {"name": name}
        if host:
            body["host"] = host
        return client.post(f"/environments/{env['id']}/services", json=body, headers=h).json()

    def make_incident(service_id):
        with SessionLocal() as db:
            inc = Incident(
                environment_id=env["id"],
                service_id=service_id,
                title="test incident",
                severity=Severity.HIGH,
                category=IncidentCategory.HIGH_LATENCY,
                status=IncidentStatus.DETECTED,
                started_at=datetime.now(timezone.utc),
                recommended_actions=[],
            )
            db.add(inc)
            db.commit()
            return inc.id

    service = make_service("payment-service", "demo-payment-service")
    state = {"restarts": [], "fail": False, "status": {"running": True, "health": "healthy"}}

    def fake_restart(name):
        if state["fail"]:
            raise AgentError("agent exploded")
        state["restarts"].append(name)
        return "restarted"

    monkeypatch.setattr(agent, "restart_container", fake_restart)
    monkeypatch.setattr(agent, "container_status", lambda name: state["status"])
    monkeypatch.setattr("app.api.remediation.time.sleep", lambda s: None)

    return {
        "user": user, "h": h, "env": env, "service": service, "state": state,
        "make_service": make_service, "make_incident": make_incident,
        "incident_id": make_incident(service["id"]),
    }


def suggest(client, r, incident_id=None):
    return client.post(f"/incidents/{incident_id or r['incident_id']}/remediations", headers=r["h"])


def test_suggest_creates_recommendation_without_executing(client, r):
    res = suggest(client, r)
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "recommended"
    assert body["container"] == "demo-payment-service"
    assert "hypothesis" in body["reason"]
    assert r["state"]["restarts"] == []


def test_suggest_twice_returns_same_recommendation(client, r):
    first = suggest(client, r).json()
    second = suggest(client, r).json()
    assert first["id"] == second["id"]


def test_suggest_requires_container_name(client, r):
    svc = r["make_service"]("no-host-service", None)
    res = suggest(client, r, r["make_incident"](svc["id"]))
    assert res.status_code == 400


def test_approve_executes_and_writes_audit_log(client, r):
    rem = suggest(client, r).json()
    res = client.post(f"/remediations/{rem['id']}/approve", headers=r["h"])
    assert res.status_code == 200
    assert res.json()["status"] == "succeeded"
    assert r["state"]["restarts"] == ["demo-payment-service"]
    logs = client.get(f"/organizations/{r['user']['org_id']}/audit-logs", headers=r["h"]).json()
    actions = {entry["action"] for entry in logs}
    assert {"remediation.suggested", "remediation.approved", "remediation.executed"} <= actions
    detail = client.get(f"/incidents/{r['incident_id']}", headers=r["h"]).json()
    assert any(e["event_type"] == "remediation_executed" for e in detail["events"])


def test_agent_failure_marks_remediation_failed(client, r):
    r["state"]["fail"] = True
    rem = suggest(client, r).json()
    res = client.post(f"/remediations/{rem['id']}/approve", headers=r["h"]).json()
    assert res["status"] == "failed"
    assert "agent exploded" in res["result_message"]


def test_container_that_never_becomes_healthy_is_failed(client, r):
    r["state"]["status"] = {"running": True, "health": "unhealthy"}
    rem = suggest(client, r).json()
    res = client.post(f"/remediations/{rem['id']}/approve", headers=r["h"]).json()
    assert res["status"] == "failed"


def test_cooldown_blocks_a_second_restart(client, r):
    first = suggest(client, r).json()
    assert client.post(f"/remediations/{first['id']}/approve", headers=r["h"]).status_code == 200
    second = suggest(client, r).json()
    blocked = client.post(f"/remediations/{second['id']}/approve", headers=r["h"])
    assert blocked.status_code == 409
    assert "cooldown" in blocked.json()["detail"].lower()
    assert len(r["state"]["restarts"]) == 1


def test_operator_can_suggest_but_not_approve(client, r, make_user):
    operator = make_user()
    with SessionLocal() as db:
        db.add(OrganizationMember(
            user_id=operator["id"], organization_id=r["user"]["org_id"], role=Role.OPERATOR))
        db.commit()
    rem = client.post(f"/incidents/{r['incident_id']}/remediations", headers=operator["headers"])
    assert rem.status_code == 201
    denied = client.post(f"/remediations/{rem.json()['id']}/approve", headers=operator["headers"])
    assert denied.status_code == 403
    assert r["state"]["restarts"] == []


def test_viewer_cannot_suggest(client, r, make_user):
    viewer = make_user()
    with SessionLocal() as db:
        db.add(OrganizationMember(
            user_id=viewer["id"], organization_id=r["user"]["org_id"], role=Role.VIEWER))
        db.commit()
    res = client.post(f"/incidents/{r['incident_id']}/remediations", headers=viewer["headers"])
    assert res.status_code == 403


def test_rejected_recommendation_cannot_be_approved(client, r):
    rem = suggest(client, r).json()
    assert client.post(f"/remediations/{rem['id']}/reject", headers=r["h"]).status_code == 200
    assert client.post(f"/remediations/{rem['id']}/approve", headers=r["h"]).status_code == 409
    assert r["state"]["restarts"] == []


def test_verify_uses_prometheus_telemetry(client, r, monkeypatch):
    def fake_instant(promql):
        if promql.startswith("max by (service) (up"):
            return [{"labels": {"service": "payment-service"}, "value": 1.0}]
        return []

    monkeypatch.setattr(prometheus, "query_instant", fake_instant)
    rem = suggest(client, r).json()
    client.post(f"/remediations/{rem['id']}/approve", headers=r["h"])
    res = client.post(f"/remediations/{rem['id']}/verify", headers=r["h"])
    assert res.status_code == 200
    assert res.json()["verified"] is True


def test_verify_requires_a_succeeded_restart(client, r):
    rem = suggest(client, r).json()
    assert client.post(f"/remediations/{rem['id']}/verify", headers=r["h"]).status_code == 409


def test_other_org_cannot_touch_remediations(client, r, make_user):
    rem = suggest(client, r).json()
    outsider = make_user()
    assert client.post(f"/remediations/{rem['id']}/approve", headers=outsider["headers"]).status_code == 404
    assert client.get(f"/incidents/{r['incident_id']}/remediations", headers=outsider["headers"]).status_code == 404