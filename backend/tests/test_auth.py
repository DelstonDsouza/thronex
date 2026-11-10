def test_register_creates_user_without_exposing_password(client):
    r = client.post(
        "/auth/register",
        json={
            "email": "a@example.com",
            "full_name": "Alice",
            "password": "password123",
            "organization_name": "Alice Org",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "a@example.com"
    assert "password" not in body
    assert "hashed_password" not in body


def test_register_duplicate_email_returns_409(client, make_user):
    make_user("dup@example.com")
    r = client.post(
        "/auth/register",
        json={
            "email": "DUP@example.com",  # case-insensitive duplicate
            "full_name": "Other",
            "password": "password123",
            "organization_name": "Other Org",
        },
    )
    assert r.status_code == 409


def test_register_short_password_returns_422(client):
    r = client.post(
        "/auth/register",
        json={
            "email": "short@example.com",
            "full_name": "Short",
            "password": "abc",
            "organization_name": "Org",
        },
    )
    assert r.status_code == 422


def test_login_wrong_password_returns_401(client, make_user):
    user = make_user()
    r = client.post(
        "/auth/login", data={"username": user["email"], "password": "wrong-password"}
    )
    assert r.status_code == 401


def test_login_unknown_email_returns_401(client):
    r = client.post(
        "/auth/login", data={"username": "nobody@example.com", "password": "password123"}
    )
    assert r.status_code == 401


def test_me_requires_token(client):
    assert client.get("/auth/me").status_code == 401


def test_me_rejects_garbage_token(client):
    r = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_me_returns_owner_membership(client, make_user):
    user = make_user()
    r = client.get("/auth/me", headers=user["headers"])
    assert r.status_code == 200
    membership = r.json()["memberships"][0]
    assert membership["role"] == "owner"
    assert membership["organization_id"] == user["org_id"]