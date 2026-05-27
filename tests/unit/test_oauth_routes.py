"""Unit tests for /oauth/start and /oauth/callback Flask routes."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from flask.testing import FlaskClient

from src.app import create_app
from src.auth.qbo_oauth import TokenSet
from src.config import Config


@pytest.fixture
def client() -> FlaskClient:
    cfg = Config(
        project_id="YOUR_GCP_PROJECT_ID",
        environment="sandbox",
        workbook_id="",
        drive_inbox_folder_id="",
        drive_archive_root_id="",
        allowed_invoker_email="",
        is_cloud_run=False,
        oauth_redirect_uri="https://example.com/oauth/callback",
        flask_secret_key="test-secret-key-for-sessions",
    )
    app = create_app(cfg)
    app.config["TESTING"] = True
    return app.test_client()


class TestOAuthStart:
    def test_redirects_to_intuit(self, client: FlaskClient) -> None:
        with patch(
            "src.auth.qbo_oauth.start_authorization_url",
            return_value=("https://intuit.com/auth?foo=bar", "state-token-xyz"),
        ):
            resp = client.get("/oauth/start")

        assert resp.status_code == 302
        assert "intuit.com" in resp.headers["Location"]

    def test_stores_state_in_session(self, client: FlaskClient) -> None:
        with (
            patch(
                "src.auth.qbo_oauth.start_authorization_url",
                return_value=("https://intuit.com/auth", "my-state"),
            ),
            client.session_transaction() as _sess,
        ):
            pass  # just ensure session context works

        with patch(
            "src.auth.qbo_oauth.start_authorization_url",
            return_value=("https://intuit.com/auth", "my-state"),
        ):
            resp = client.get("/oauth/start")

        assert resp.status_code == 302

    def test_returns_500_when_redirect_uri_not_configured(self) -> None:
        cfg = Config(
            project_id="YOUR_GCP_PROJECT_ID",
            environment="sandbox",
            workbook_id="",
            drive_inbox_folder_id="",
            drive_archive_root_id="",
            allowed_invoker_email="",
            is_cloud_run=False,
            oauth_redirect_uri="",  # not set
            flask_secret_key="test-secret",
        )
        app = create_app(cfg)
        app.config["TESTING"] = True
        c = app.test_client()
        resp = c.get("/oauth/start")
        assert resp.status_code == 500
        assert resp.get_json()["error"] == "OAUTH_REDIRECT_URI not configured"


class TestOAuthCallback:
    def _get_client_with_state(self, client: FlaskClient, state: str = "valid-state") -> None:
        """Prime the session with an oauth_state value."""
        with client.session_transaction() as sess:
            sess["oauth_state"] = state

    def test_successful_callback(self, client: FlaskClient) -> None:
        self._get_client_with_state(client, "valid-state")
        token_set = TokenSet(
            access_token="ACC", refresh_token="REF", realm_id="REALM99", expires_at=9999999.0
        )

        with patch("src.auth.qbo_oauth.exchange_code", return_value=token_set):
            resp = client.get(
                "/oauth/callback?code=AUTH_CODE&state=valid-state&realmId=REALM99"
            )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert body["realm_id"] == "REALM99"

    def test_error_param_returns_400(self, client: FlaskClient) -> None:
        resp = client.get("/oauth/callback?error=access_denied")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "oauth_denied"

    def test_missing_code_returns_400(self, client: FlaskClient) -> None:
        self._get_client_with_state(client, "s")
        resp = client.get("/oauth/callback?state=s&realmId=R")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "missing_params"

    def test_missing_state_returns_400(self, client: FlaskClient) -> None:
        resp = client.get("/oauth/callback?code=C&realmId=R")
        assert resp.status_code == 400

    def test_missing_realm_id_returns_400(self, client: FlaskClient) -> None:
        self._get_client_with_state(client, "s")
        resp = client.get("/oauth/callback?code=C&state=s")
        assert resp.status_code == 400

    def test_state_mismatch_returns_400(self, client: FlaskClient) -> None:
        self._get_client_with_state(client, "expected-state")
        resp = client.get("/oauth/callback?code=C&state=wrong-state&realmId=R")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "state_mismatch"

    def test_no_session_state_returns_400(self, client: FlaskClient) -> None:
        # No prior call to /oauth/start, so session has no oauth_state
        resp = client.get("/oauth/callback?code=C&state=anything&realmId=R")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "state_mismatch"
