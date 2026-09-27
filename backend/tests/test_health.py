from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app

from .conftest import requires_db

client = TestClient(app)


@requires_db
def test_health_ok(db_session):
    # "ok" means the database answers (the deploy rolls back when it doesn't):
    # tests/test_safe_deploys.py has the database-down case.
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        resp = client.get("/api/health")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "GameSense"


def test_me_requires_auth():
    # No bearer token → 403 from HTTPBearer.
    assert client.get("/api/auth/me").status_code == 403
