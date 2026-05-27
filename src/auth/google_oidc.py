"""Verify Google-issued OIDC identity tokens on inbound requests.

Used to authenticate calls from Apps Script (operator's email) and from
Cloud Scheduler (Scheduler service account) on /push and /pull.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def verify_token(id_token: str, expected_email: str) -> None:
    """Verify a Google OIDC token and assert the email matches expected.

    Raises ValueError if the token is invalid, expired, the email doesn't
    match, or the email is unverified.
    """
    import google.auth.transport.requests
    import google.oauth2.id_token

    request = google.auth.transport.requests.Request()
    try:
        claims = google.oauth2.id_token.verify_oauth2_token(id_token, request)
    except Exception as exc:
        raise ValueError(f"invalid OIDC token: {exc}") from exc

    email: str = claims.get("email", "")
    if email.lower() != expected_email.lower():
        raise ValueError(
            f"token email {email!r} does not match expected {expected_email!r}"
        )

    if not claims.get("email_verified", False):
        raise ValueError(f"token email {email!r} is not verified by Google")

    log.debug("verified OIDC token for %s", email)
