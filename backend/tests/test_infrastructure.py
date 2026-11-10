import pytest

from app.core.database import SessionLocal
from app.models import OrganizationMember, Role


@pytest.fixture
def stack(client, make_user):
    """A user with one application, one staging environment and one service."""
    user = make_user()
    h = user["headers"]
    app = client.post(
        f"/organizations/{user['org_id']}/applications",
        json={"name": "E-commerce Platform"},
        headers=h,
    ).json()
    env = client.post(
        f"/applications/{app['id']}/environments",
        json={"name": "Staging", "env_type": "staging", "chaos_enabled": True},
        headers=h,
    ).json()
    service = client.post(
        f"/environments/{env['id']}/services",
        json={
            "name": "payment-service",
            "host": "payment-service",
            "port": 8000,
            "health_check_path": "/health",
        },
        headers=h,
    ).json()
    return {"user": user, "app": app, "env": env, "service": service}


# ---------- Applications ----------
def test_duplicate_application_name_returns_409(client, stack):
    user = stack["user"]
    r = client.post(
        f"/organizations/{user['org_id']}/applications",
        json={"name": "E-commerce Platform"},
        headers=user["headers"],
    )
    assert r.status_code == 409


def test_list_applications(client, stack):
    user = stack["user"]
    r = client.get(
        f"/organizations/{user['org_id']}/applications", headers=user["headers"]
    )
    assert r.status_code == 200
    assert [a["name"] for a in r.json()] == ["E-commerce Platform"]


def test_requests_without_token_return_401(client, stack):
    assert client.get(f"/applications/{stack['app']['id']}").status_code == 401


# ---------- Environments and the chaos safety rule ----------
def test_cannot_create_production_with_chaos_enabled(client, stack):
    r = client.post(
        f"/applications/{stack['app']['id']}/environments",
        json={"name": "Production", "env_type": "production", "chaos_enabled": True},
        headers=stack["user"]["headers"],
    )
    assert r.status_code == 400


def test_can_create_production_with_chaos_disabled(client, stack):
    r = client.post(
        f"/applications/{stack['app']['id']}/environments",
        json={"name": "Production", "env_type": "production", "chaos_enabled": False},
        headers=stack["user"]["headers"],
    )
    assert r.status_code == 201
    assert r.json()["chaos_enabled"] is False


def test_cannot_turn_chaos_environment_into_production(client, stack):
    # Staging has chaos enabled; switching its type to production must be blocked.
    r = client.patch(
        f"/environments/{stack['env']['id']}",
        json={"env_type": "production"},
        headers=stack["user"]["headers"],
    )
    assert r.status_code == 400


def test_duplicate_environment_name_returns_409(client, stack):
    r = client.post(
        f"/applications/{stack['app']['id']}/environments",
        json={"name": "Staging", "env_type": "staging"},
        headers=stack["user"]["headers"],
    )
    assert r.status_code == 409


# ---------- Services ----------
def test_duplicate_service_name_returns_409(client, stack):
    r = client.post(
        f"/environments/{stack['env']['id']}/services",
        json={"name": "payment-service"},
        headers=stack["user"]["headers"],
    )
    assert r.status_code == 409


def test_service_defaults(stack):
    service = stack["service"]
    assert service["status"] == "unknown"
    assert service["is_active"] is True


def test_invalid_port_returns_422(client, stack):
    r = client.post(
        f"/environments/{stack['env']['id']}/services",
        json={"name": "bad-port", "port": 70000},
        headers=stack["user"]["headers"],
    )
    assert r.status_code == 422


def test_health_path_must_start_with_slash(client, stack):
    r = client.post(
        f"/environments/{stack['env']['id']}/services",
        json={"name": "bad-path", "health_check_path": "health"},
        headers=stack["user"]["headers"],
    )
    assert r.status_code == 422


def test_patch_service_changes_only_sent_fields(client, stack):
    r = client.patch(
        f"/services/{stack['service']['id']}",
        json={"port": 8001},
        headers=stack["user"]["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["port"] == 8001
    assert body["name"] == "payment-service"  # untouched
    assert body["host"] == "payment-service"  # untouched


def test_deactivate_service(client, stack):
    r = client.patch(
        f"/services/{stack['service']['id']}",
        json={"is_active": False},
        headers=stack["user"]["headers"],
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_delete_service(client, stack):
    h = stack["user"]["headers"]
    sid = stack["service"]["id"]
    assert client.delete(f"/services/{sid}", headers=h).status_code == 204
    assert client.get(f"/services/{sid}", headers=h).status_code == 404


def test_deleting_application_cascades_to_services(client, stack):
    h = stack["user"]["headers"]
    assert client.delete(f"/applications/{stack['app']['id']}", headers=h).status_code == 204
    assert client.get(f"/services/{stack['service']['id']}", headers=h).status_code == 404
    assert client.get(f"/environments/{stack['env']['id']}", headers=h).status_code == 404


# ---------- Organization isolation ----------
def test_other_org_cannot_see_or_modify_anything(client, make_user, stack):
    outsider = make_user()
    h = outsider["headers"]
    app_id = stack["app"]["id"]
    env_id = stack["env"]["id"]
    service_id = stack["service"]["id"]

    assert client.get(f"/applications/{app_id}", headers=h).status_code == 404
    assert client.get(f"/environments/{env_id}", headers=h).status_code == 404
    assert client.get(f"/services/{service_id}", headers=h).status_code == 404
    assert client.get(f"/environments/{env_id}/services", headers=h).status_code == 404
    assert (
        client.get(
            f"/organizations/{stack['user']['org_id']}/applications", headers=h
        ).status_code
        == 404
    )
    assert client.delete(f"/services/{service_id}", headers=h).status_code == 404
    assert (
        client.post(
            f"/environments/{env_id}/services", json={"name": "evil"}, headers=h
        ).status_code
        == 404
    )


# ---------- Role checks ----------
def test_viewer_can_read_but_not_write(client, make_user, stack):
    owner = stack["user"]
    viewer = make_user()

    # Add the second user to the first user's organization as a VIEWER.
    with SessionLocal() as db:
        db.add(
            OrganizationMember(
                user_id=viewer["id"], organization_id=owner["org_id"], role=Role.VIEWER
            )
        )
        db.commit()

    h = viewer["headers"]
    env_id = stack["env"]["id"]

    assert client.get(f"/environments/{env_id}/services", headers=h).status_code == 200
    assert (
        client.post(
            f"/environments/{env_id}/services", json={"name": "nope"}, headers=h
        ).status_code
        == 403
    )
    assert (
        client.delete(f"/services/{stack['service']['id']}", headers=h).status_code
        == 403
    )