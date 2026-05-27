"""QBO OAuth 2.0 handler.

Responsibilities:
  - Build the Intuit authorize URL with state token (CSRF protection).
  - Exchange authorization code for access + refresh tokens.
  - Refresh access tokens using CAS semantics on the Secret Manager token so
    concurrent Cloud Run instances don't stomp each other's refresh.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from src.config import Config
from src.utils.secrets import SecretVersionConflict, fetch_secret, write_secret, write_secret_cas

log = logging.getLogger(__name__)

_MAX_CAS_RETRIES = 3


@dataclass(frozen=True)
class TokenSet:
    """Snapshot of live QBO credentials returned from a token operation."""

    access_token: str
    refresh_token: str
    realm_id: str
    expires_at: float  # unix timestamp


def _cred_secret_name(base: str, cfg: Config) -> str:
    """Secret name for shared credentials (client_id / client_secret)."""
    return f"{base}-{cfg.credential_suffix}"


def _token_secret_name(base: str, cfg: Config) -> str:
    """Secret name for per-company / per-env tokens (refresh_token / realm_id)."""
    return f"{base}-{cfg.secret_suffix}"


def _make_auth_client(
    cfg: Config,
    client_id: str,
    client_secret: str,
    *,
    refresh_token: str | None = None,
) -> object:
    from intuitlib.client import AuthClient

    return AuthClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=cfg.oauth_redirect_uri,
        environment="sandbox" if cfg.is_sandbox else "production",
        refresh_token=refresh_token,
    )


def start_authorization_url(cfg: Config) -> tuple[str, str]:
    """Return (authorization_url, state_token) for the Intuit OAuth flow.

    The caller (Flask route) stores the state_token in the session so it can
    be verified when Intuit redirects back to /oauth/callback.
    """
    from intuitlib.enums import Scopes

    client_id = fetch_secret(cfg.project_id, _cred_secret_name("qbo-client-id", cfg)).payload
    client = _make_auth_client(cfg, client_id, "")
    url = client.get_authorization_url([Scopes.ACCOUNTING])  # type: ignore[attr-defined]
    return url, client.state_token  # type: ignore[attr-defined]


def exchange_code(cfg: Config, code: str, realm_id: str) -> TokenSet:
    """Exchange an authorization code for tokens and persist to Secret Manager.

    This is the one-time bootstrap path.  We do an unconditional write (not
    CAS) because the admin is explicitly re-authorizing.
    """
    client_id = fetch_secret(cfg.project_id, _cred_secret_name("qbo-client-id", cfg)).payload
    client_secret = fetch_secret(cfg.project_id, _cred_secret_name("qbo-client-secret", cfg)).payload

    client = _make_auth_client(cfg, client_id, client_secret)
    client.get_bearer_token(code, realm_id=realm_id)  # type: ignore[attr-defined]

    write_secret(cfg.project_id, _token_secret_name("qbo-refresh-token", cfg), client.refresh_token)  # type: ignore[attr-defined]
    write_secret(cfg.project_id, _token_secret_name("qbo-realm-id", cfg), realm_id)

    log.info("OAuth exchange complete; refresh token persisted for realm %s", realm_id)
    return TokenSet(
        access_token=client.access_token,  # type: ignore[attr-defined]
        refresh_token=client.refresh_token,  # type: ignore[attr-defined]
        realm_id=realm_id,
        expires_at=time.time() + int(client.expires_in or 3600),  # type: ignore[attr-defined]
    )


def get_access_token(cfg: Config) -> TokenSet:
    """Return a fresh access token, rotating the stored refresh token."""
    return refresh_if_needed(cfg)


def refresh_if_needed(cfg: Config) -> TokenSet:
    """Obtain a fresh access token using the stored refresh token.

    Uses compare-and-swap when persisting the rotated refresh token to prevent
    concurrent refreshes from clobbering each other.  Retries up to
    _MAX_CAS_RETRIES times on conflict before raising.
    """
    client_id = fetch_secret(cfg.project_id, _cred_secret_name("qbo-client-id", cfg)).payload
    client_secret = fetch_secret(cfg.project_id, _cred_secret_name("qbo-client-secret", cfg)).payload
    rt_ref = fetch_secret(cfg.project_id, _token_secret_name("qbo-refresh-token", cfg))
    realm_ref = fetch_secret(cfg.project_id, _token_secret_name("qbo-realm-id", cfg))

    client = _make_auth_client(cfg, client_id, client_secret, refresh_token=rt_ref.payload)

    for attempt in range(_MAX_CAS_RETRIES):
        client.refresh()  # type: ignore[attr-defined]
        try:
            write_secret_cas(
                cfg.project_id,
                _token_secret_name("qbo-refresh-token", cfg),
                client.refresh_token,  # type: ignore[attr-defined]
                rt_ref.version_id,
            )
            break
        except SecretVersionConflict:
            if attempt == _MAX_CAS_RETRIES - 1:
                raise
            rt_ref = fetch_secret(cfg.project_id, _token_secret_name("qbo-refresh-token", cfg))
            client.refresh_token = rt_ref.payload  # type: ignore[attr-defined]
            log.warning("CAS conflict on refresh token; retrying (attempt %d)", attempt + 2)

    return TokenSet(
        access_token=client.access_token,  # type: ignore[attr-defined]
        refresh_token=client.refresh_token,  # type: ignore[attr-defined]
        realm_id=realm_ref.payload,
        expires_at=time.time() + int(client.expires_in or 3600),  # type: ignore[attr-defined]
    )
