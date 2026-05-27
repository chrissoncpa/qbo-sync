"""Unit tests for src.auth.google_oidc."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.auth.google_oidc import verify_token


class TestVerifyToken:
    def test_valid_token_passes(self) -> None:
        claims = {"email": "admin@example.com", "email_verified": True}
        with patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims):
            verify_token("fake.jwt.token", "admin@example.com")  # should not raise

    def test_case_insensitive_email_match(self) -> None:
        claims = {"email": "Admin@Example.COM", "email_verified": True}
        with patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims):
            verify_token("token", "admin@example.com")

    def test_email_mismatch_raises(self) -> None:
        claims = {"email": "other@example.com", "email_verified": True}
        with patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims):
            with pytest.raises(ValueError, match="does not match expected"):
                verify_token("token", "admin@example.com")

    def test_unverified_email_raises(self) -> None:
        claims = {"email": "admin@example.com", "email_verified": False}
        with patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims):
            with pytest.raises(ValueError, match="not verified"):
                verify_token("token", "admin@example.com")

    def test_invalid_token_raises(self) -> None:
        with patch(
            "google.oauth2.id_token.verify_oauth2_token",
            side_effect=ValueError("signature expired"),
        ):
            with pytest.raises(ValueError, match="invalid OIDC token"):
                verify_token("bad.token", "admin@example.com")
