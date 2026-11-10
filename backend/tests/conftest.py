import os

# Must happen BEFORE importing the app, so it connects to the TEST database.
TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://thronex:change_me_local_only@localhost:5433/thronex_test",
)
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-automated-tests")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

# Safety guard: never run tests against a non-test database.
assert (make_url(TEST_DB_URL).database or "").endswith("_test"), (
    "Refusing to run tests: database name must end with '_test'"
)


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def clean_db():
    """Empties every table after each test so tests don't affect each other."""
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_user(client):
    """Factory: registers + logs in a user, returns auth headers and org id."""
    counter = {"n": 0}

    def _make(email: str | None = None) -> dict:
        counter["n"] += 1
        n = counter["n"]
        email = email or f"user{n}@example.com"
        r = client.post(
            "/auth/register",
            json={
                "email": email,
                "full_name": f"User {n}",
                "password": "password123",
                "organization_name": f"Org {n}",
            },
        )
        assert r.status_code == 201, r.text
        login = client.post(
            "/auth/login", data={"username": email, "password": "password123"}
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        me = client.get("/auth/me", headers=headers).json()
        return {
            "id": me["id"],
            "email": email,
            "headers": headers,
            "org_id": me["memberships"][0]["organization_id"],
        }

    return _make