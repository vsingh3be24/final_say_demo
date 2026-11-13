"""Health endpoints. The container healthcheck in compose.yaml probes
``/api/health/ready``, so a regression there stalls every deployment."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_liveness_ok(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_ok_when_database_reachable(client: TestClient) -> None:
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
