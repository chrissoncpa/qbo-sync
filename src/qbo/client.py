"""Wrapper that builds a ready-to-use python-quickbooks client.

Reads credentials from Secret Manager, lets the intuitlib AuthClient perform
one token refresh (which rotates the refresh token), then persists the new
refresh token back via CAS.  If a concurrent instance already rotated the
token, we log a warning and continue — the access token from our refresh is
still valid for ~1 hour.
"""

from __future__ import annotations

import logging

from src.config import Config
from src.utils.secrets import SecretVersionConflict, fetch_secret, write_secret_cas

log = logging.getLogger(__name__)


def get_qbo_client(cfg: Config) -> object:
    """Return an authenticated QuickBooks client for cfg's environment.

    Side-effect: rotates the stored refresh token in Secret Manager.
    """
    from intuitlib.client import AuthClient
    from quickbooks import QuickBooks

    cred = cfg.credential_suffix
    client_id = fetch_secret(cfg.project_id, f"qbo-client-id-{cred}").payload
    client_secret = fetch_secret(cfg.project_id, f"qbo-client-secret-{cred}").payload
    rt_ref = fetch_secret(cfg.project_id, f"qbo-refresh-token-{cfg.secret_suffix}")
    realm_ref = fetch_secret(cfg.project_id, f"qbo-realm-id-{cfg.secret_suffix}")

    auth_client = AuthClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=cfg.oauth_redirect_uri,
        environment="sandbox" if cfg.is_sandbox else "production",
        refresh_token=rt_ref.payload,
    )

    # QuickBooks.__new__ calls auth_client.refresh() immediately, rotating the token.
    qb = QuickBooks(
        auth_client=auth_client,
        refresh_token=rt_ref.payload,
        company_id=realm_ref.payload,
        minorversion=75,
    )

    try:
        write_secret_cas(
            cfg.project_id,
            f"qbo-refresh-token-{cfg.secret_suffix}",  # per-company / per-env suffix
            auth_client.refresh_token,
            rt_ref.version_id,
        )
    except SecretVersionConflict:
        # A concurrent instance already rotated the token; our access token
        # from this refresh is still valid for the duration of this request.
        log.warning("concurrent refresh token rotation detected; continuing with current session")

    return qb
