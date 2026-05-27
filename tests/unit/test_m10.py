"""Unit tests for M10: /readyz, auth_required in /health, production safety warning."""

from __future__ import annotations

import logging

import pytest

from src.app import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("WORKBOOK_ID", "WB123")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "https://example.com/oauth/callback")
    app = create_app()
    return app.test_client()


@pytest.fixture
def app_factory(monkeypatch):
    """Return a factory that creates an app with overridden env vars."""
    def _make(**overrides):
        base = {
            "WORKBOOK_ID": "WB123",
            "OAUTH_REDIRECT_URI": "https://example.com/oauth/callback",
            "ALLOWED_INVOKER_EMAIL": "",
            "ENVIRONMENT": "sandbox",
        }
        base.update(overrides)
        for k, v in base.items():
            monkeypatch.setenv(k, v)
        return create_app()
    return _make


# ---------------------------------------------------------------------------
# /health: auth_required field
# ---------------------------------------------------------------------------

class TestHealthAuthRequired:
    def test_auth_required_false_when_no_email(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json()["auth_required"] is False

    def test_auth_required_true_when_email_set(self, app_factory):
        app = app_factory(ALLOWED_INVOKER_EMAIL="invoker@example.com")
        with app.test_client() as c:
            resp = c.get("/health")
            assert resp.status_code == 200
            assert resp.get_json()["auth_required"] is True


# ---------------------------------------------------------------------------
# /readyz
# ---------------------------------------------------------------------------

class TestReadyz:
    def test_ok_when_configured(self, client):
        resp = client.get("/readyz")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

    def test_503_when_workbook_missing(self, app_factory):
        app = app_factory(WORKBOOK_ID="")
        with app.test_client() as c:
            resp = c.get("/readyz")
            assert resp.status_code == 503
            body = resp.get_json()
            assert body["status"] == "not_ready"
            assert any("WORKBOOK_ID" in issue for issue in body["issues"])

    def test_503_when_redirect_uri_missing(self, app_factory):
        app = app_factory(OAUTH_REDIRECT_URI="")
        with app.test_client() as c:
            resp = c.get("/readyz")
            assert resp.status_code == 503
            body = resp.get_json()
            assert any("OAUTH_REDIRECT_URI" in issue for issue in body["issues"])

    def test_503_lists_all_issues(self, app_factory):
        app = app_factory(WORKBOOK_ID="", OAUTH_REDIRECT_URI="")
        with app.test_client() as c:
            resp = c.get("/readyz")
            assert resp.status_code == 503
            assert len(resp.get_json()["issues"]) == 2


# ---------------------------------------------------------------------------
# Production safety warning
# ---------------------------------------------------------------------------

class TestProductionSafetyWarning:
    def test_warns_when_production_without_auth(self, app_factory, caplog):
        with caplog.at_level(logging.WARNING):
            app_factory(ENVIRONMENT="production", ALLOWED_INVOKER_EMAIL="")
        assert any("unauthenticated" in r.message for r in caplog.records)

    def test_no_warn_when_production_with_auth(self, app_factory, caplog):
        with caplog.at_level(logging.WARNING):
            app_factory(ENVIRONMENT="production", ALLOWED_INVOKER_EMAIL="invoker@example.com")
        assert not any("unauthenticated" in r.message for r in caplog.records)

    def test_no_warn_in_sandbox_without_auth(self, app_factory, caplog):
        with caplog.at_level(logging.WARNING):
            app_factory(ENVIRONMENT="sandbox", ALLOWED_INVOKER_EMAIL="")
        assert not any("unauthenticated" in r.message for r in caplog.records)
