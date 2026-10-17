from fastapi.testclient import TestClient

from app.main import app


def test_health():
    assert TestClient(app).get("/api/health").json() == {"status": "ok"}


def test_rejects_foreign_host_header():
    client = TestClient(app)
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/api/health", headers={"host": "localhost:5173"}).status_code == 200
    assert client.get("/api/health").status_code == 200
