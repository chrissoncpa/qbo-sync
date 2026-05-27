"""Unit tests for src.auth.qbo_oauth."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from src.auth.qbo_oauth import TokenSet, exchange_code, get_access_token, refresh_if_needed, start_authorization_url
from src.utils.secrets import SecretRef, SecretVersionConflict


def _cfg(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "https://example.com/oauth/callback")
    from src.config import Config

    return Config(
        project_id="YOUR_GCP_PROJECT_ID",
        environment="sandbox",
        workbook_id="",
        drive_inbox_folder_id="",
        drive_archive_root_id="",
        allowed_invoker_email="",
        is_cloud_run=False,
        oauth_redirect_uri="https://example.com/oauth/callback",
        flask_secret_key="test-secret",
    )


def _secret_ref(name: str, payload: str, version: str = "1") -> SecretRef:
    return SecretRef(name=name, version_id=version, payload=payload)


class TestStartAuthorizationUrl:
    def test_returns_url_and_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _cfg(monkeypatch)
        fake_client = MagicMock()
        fake_client.get_authorization_url.return_value = "https://intuit.com/auth?foo=bar"
        fake_client.state_token = "csrf-abc"

        with (
            patch("src.auth.qbo_oauth.fetch_secret", return_value=_secret_ref("qbo-client-id-sandbox", "CLIENT_ID")),
            patch("src.auth.qbo_oauth._make_auth_client", return_value=fake_client),
        ):
            url, state = start_authorization_url(cfg)

        assert url == "https://intuit.com/auth?foo=bar"
        assert state == "csrf-abc"

    def test_fetches_client_id_from_secret_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _cfg(monkeypatch)
        fake_client = MagicMock()
        fake_client.get_authorization_url.return_value = "https://intuit.com/auth"
        fake_client.state_token = "state-xyz"

        with (
            patch("src.auth.qbo_oauth.fetch_secret", return_value=_secret_ref("qbo-client-id-sandbox", "MY_CLIENT_ID")) as mock_fetch,
            patch("src.auth.qbo_oauth._make_auth_client", return_value=fake_client),
        ):
            start_authorization_url(cfg)

        mock_fetch.assert_called_once_with("YOUR_GCP_PROJECT_ID", "qbo-client-id-sandbox")


class TestExchangeCode:
    def test_exchanges_code_and_persists_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _cfg(monkeypatch)
        fake_client = MagicMock()
        fake_client.access_token = "ACCESS"
        fake_client.refresh_token = "REFRESH"
        fake_client.expires_in = 3600

        secrets_side_effect = [
            _secret_ref("qbo-client-id-sandbox", "CID"),
            _secret_ref("qbo-client-secret-sandbox", "CSECRET"),
        ]

        with (
            patch("src.auth.qbo_oauth.fetch_secret", side_effect=secrets_side_effect),
            patch("src.auth.qbo_oauth._make_auth_client", return_value=fake_client),
            patch("src.auth.qbo_oauth.write_secret") as mock_write,
        ):
            result = exchange_code(cfg, code="AUTH_CODE", realm_id="REALM123")

        fake_client.get_bearer_token.assert_called_once_with("AUTH_CODE", realm_id="REALM123")
        assert mock_write.call_count == 2
        mock_write.assert_any_call("YOUR_GCP_PROJECT_ID", "qbo-refresh-token-sandbox", "REFRESH")
        mock_write.assert_any_call("YOUR_GCP_PROJECT_ID", "qbo-realm-id-sandbox", "REALM123")

        assert isinstance(result, TokenSet)
        assert result.access_token == "ACCESS"
        assert result.refresh_token == "REFRESH"
        assert result.realm_id == "REALM123"
        assert result.expires_at > time.time()


class TestRefreshIfNeeded:
    def _setup(self, monkeypatch: pytest.MonkeyPatch, fake_client: MagicMock):
        cfg = _cfg(monkeypatch)
        secrets_side_effect = [
            _secret_ref("qbo-client-id-sandbox", "CID"),
            _secret_ref("qbo-client-secret-sandbox", "CSECRET"),
            _secret_ref("qbo-refresh-token-sandbox", "OLD_RT", version="5"),
            _secret_ref("qbo-realm-id-sandbox", "REALM42"),
        ]
        return cfg, secrets_side_effect

    def test_refreshes_and_writes_new_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_client = MagicMock()
        fake_client.access_token = "NEW_ACCESS"
        fake_client.refresh_token = "NEW_RT"
        fake_client.expires_in = 3600
        cfg, secrets_se = self._setup(monkeypatch, fake_client)

        with (
            patch("src.auth.qbo_oauth.fetch_secret", side_effect=secrets_se),
            patch("src.auth.qbo_oauth._make_auth_client", return_value=fake_client),
            patch("src.auth.qbo_oauth.write_secret_cas") as mock_cas,
        ):
            result = refresh_if_needed(cfg)

        fake_client.refresh.assert_called_once()
        mock_cas.assert_called_once_with(
            "YOUR_GCP_PROJECT_ID", "qbo-refresh-token-sandbox", "NEW_RT", "5"
        )
        assert result.access_token == "NEW_ACCESS"
        assert result.realm_id == "REALM42"

    def test_retries_on_cas_conflict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_client = MagicMock()
        fake_client.access_token = "NEW_ACCESS"
        fake_client.refresh_token = "NEW_RT"
        fake_client.expires_in = 3600
        cfg, _ = self._setup(monkeypatch, fake_client)

        initial_secrets = [
            _secret_ref("qbo-client-id-sandbox", "CID"),
            _secret_ref("qbo-client-secret-sandbox", "CSECRET"),
            _secret_ref("qbo-refresh-token-sandbox", "OLD_RT", version="5"),
            _secret_ref("qbo-realm-id-sandbox", "REALM42"),
        ]
        retry_rt = _secret_ref("qbo-refresh-token-sandbox", "CONCURRENT_RT", version="6")

        cas_calls = [
            SecretVersionConflict("qbo-refresh-token-sandbox", "5", "6"),
            _secret_ref("qbo-refresh-token-sandbox", "NEW_RT", version="7"),
        ]

        with (
            patch("src.auth.qbo_oauth.fetch_secret", side_effect=initial_secrets + [retry_rt]),
            patch("src.auth.qbo_oauth._make_auth_client", return_value=fake_client),
            patch("src.auth.qbo_oauth.write_secret_cas", side_effect=cas_calls),
        ):
            result = refresh_if_needed(cfg)

        assert fake_client.refresh.call_count == 2
        assert result.access_token == "NEW_ACCESS"

    def test_raises_after_max_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_client = MagicMock()
        fake_client.refresh_token = "RT"
        fake_client.expires_in = 3600
        cfg, initial_secrets = self._setup(monkeypatch, fake_client)

        retry_secrets = [
            _secret_ref("qbo-refresh-token-sandbox", f"RT_{i}", version=str(i))
            for i in range(10)
        ]

        with (
            patch("src.auth.qbo_oauth.fetch_secret", side_effect=initial_secrets + retry_secrets),
            patch("src.auth.qbo_oauth._make_auth_client", return_value=fake_client),
            patch(
                "src.auth.qbo_oauth.write_secret_cas",
                side_effect=SecretVersionConflict("qbo-refresh-token-sandbox", "x", "y"),
            ),
        ):
            with pytest.raises(SecretVersionConflict):
                refresh_if_needed(cfg)


class TestGetAccessToken:
    def test_delegates_to_refresh_if_needed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _cfg(monkeypatch)
        expected = TokenSet(access_token="A", refresh_token="R", realm_id="ID", expires_at=99999.0)

        with patch("src.auth.qbo_oauth.refresh_if_needed", return_value=expected) as mock_refresh:
            result = get_access_token(cfg)

        mock_refresh.assert_called_once_with(cfg)
        assert result is expected
