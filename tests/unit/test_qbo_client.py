"""Unit tests for src.qbo.client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.qbo.client import get_qbo_client
from src.utils.secrets import SecretRef, SecretVersionConflict


def _ref(name: str, payload: str, version: str = "1") -> SecretRef:
    return SecretRef(name=name, version_id=version, payload=payload)


def _cfg():
    from src.config import Config

    return Config(
        project_id="YOUR_GCP_PROJECT_ID",
        environment="sandbox",
        workbook_id="WB123",
        drive_inbox_folder_id="",
        drive_archive_root_id="",
        allowed_invoker_email="",
        is_cloud_run=False,
        oauth_redirect_uri="https://example.com/oauth/callback",
        flask_secret_key="test",
    )


class TestGetQboClient:
    def _secrets(self) -> list[SecretRef]:
        return [
            _ref("qbo-client-id-sandbox", "CID"),
            _ref("qbo-client-secret-sandbox", "CSECRET"),
            _ref("qbo-refresh-token-sandbox", "OLD_RT", version="3"),
            _ref("qbo-realm-id-sandbox", "REALM42"),
        ]

    def test_returns_quickbooks_instance(self) -> None:
        cfg = _cfg()
        mock_auth = MagicMock()
        mock_auth.refresh_token = "NEW_RT"
        mock_qb = MagicMock()

        with (
            patch("src.qbo.client.fetch_secret", side_effect=self._secrets()),
            patch("src.qbo.client.write_secret_cas"),
            patch("intuitlib.client.AuthClient", return_value=mock_auth),
            patch("quickbooks.QuickBooks", return_value=mock_qb),
        ):
            result = get_qbo_client(cfg)

        assert result is mock_qb

    def test_persists_rotated_refresh_token(self) -> None:
        cfg = _cfg()
        mock_auth = MagicMock()
        mock_auth.refresh_token = "NEW_RT"

        with (
            patch("src.qbo.client.fetch_secret", side_effect=self._secrets()),
            patch("src.qbo.client.write_secret_cas") as mock_cas,
            patch("intuitlib.client.AuthClient", return_value=mock_auth),
            patch("quickbooks.QuickBooks", return_value=MagicMock()),
        ):
            get_qbo_client(cfg)

        mock_cas.assert_called_once_with(
            "YOUR_GCP_PROJECT_ID", "qbo-refresh-token-sandbox", "NEW_RT", "3"
        )

    def test_continues_on_cas_conflict(self) -> None:
        cfg = _cfg()
        mock_auth = MagicMock()
        mock_auth.refresh_token = "NEW_RT"

        with (
            patch("src.qbo.client.fetch_secret", side_effect=self._secrets()),
            patch(
                "src.qbo.client.write_secret_cas",
                side_effect=SecretVersionConflict("qbo-refresh-token-sandbox", "3", "4"),
            ),
            patch("intuitlib.client.AuthClient", return_value=mock_auth),
            patch("quickbooks.QuickBooks", return_value=MagicMock()),
        ):
            result = get_qbo_client(cfg)  # should not raise

        assert result is not None
