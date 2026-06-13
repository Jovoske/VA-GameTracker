from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "GameSense"


def test_me_requires_auth():
    # No bearer token → 403 from HTTPBearer.
    assert client.get("/api/auth/me").status_code == 403
