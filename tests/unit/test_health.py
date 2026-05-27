"""Smoke tests for the M1 /health endpoint."""

from __future__ import annotations

import pytest
from flask.testing import FlaskClient

from src import __version__
from src.app import create_app


@pytest.fixture
def client() -> FlaskClient:
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_health_returns_ok(client: FlaskClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["environment"] == "sandbox"
    assert body["project"] == "YOUR_GCP_PROJECT_ID"


def test_unimplemented_routes_return_501(client: FlaskClient) -> None:
    """Stubs should announce themselves clearly until the relevant milestone lands."""
    # /push implemented in M5, /pull in M3, /oauth/* in M2 — all removed from this list
    for method, path, expected_milestone in []:
        resp = getattr(client, method)(path)
        assert resp.status_code == 501, f"{method.upper()} {path}"
        body = resp.get_json()
        assert body["error"] == "not_implemented"
        assert body["milestone"] == expected_milestone


def test_unknown_route_404(client: FlaskClient) -> None:
    resp = client.get("/nope")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "not_found"}
