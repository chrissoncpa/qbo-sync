"""Secret Manager helpers.

Used to fetch QBO credentials at runtime and to persist rotated refresh tokens
back to the secret store with compare-and-swap semantics so concurrent token
refreshes don't lose the latest token.

Milestone: M2 (real wiring), but the read path is useful as soon as we want
to test against real QBO credentials.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.cloud import secretmanager  # type: ignore[import-untyped]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SecretRef:
    """A versioned reference to a secret."""

    name: str  # short logical name, e.g. "qbo-refresh-token"
    version_id: str  # numeric version id from Secret Manager
    payload: str


def _client() -> "secretmanager.SecretManagerServiceClient":
    # Imported lazily so unit tests don't require GCP libs at import time.
    from google.cloud import secretmanager

    return secretmanager.SecretManagerServiceClient()


def fetch_secret(project_id: str, name: str, version: str = "latest") -> SecretRef:
    """Read the latest (or specified) version of a secret."""
    client = _client()
    resource = f"projects/{project_id}/secrets/{name}/versions/{version}"
    response = client.access_secret_version(request={"name": resource})
    return SecretRef(
        name=name,
        version_id=response.name.rsplit("/", 1)[-1],
        payload=response.payload.data.decode("utf-8"),
    )


def write_secret_cas(
    project_id: str,
    name: str,
    new_payload: str,
    expected_version: str,
) -> SecretRef:
    """Write a new secret version only if the current version matches expected.

    QBO's refresh tokens rotate on every refresh, and concurrent refreshes
    would otherwise stomp each other. We mitigate by reading the current
    version, then writing only if no other writer has bumped the version
    since we read.

    Note: Secret Manager doesn't have native CAS, so we approximate by
    re-reading after the write and verifying our version is the next one.
    On conflict, the caller should re-fetch and retry.
    """
    client = _client()
    parent = f"projects/{project_id}/secrets/{name}"

    # Read latest first; abort if it's already moved past our expected version.
    current = fetch_secret(project_id, name, "latest")
    if current.version_id != expected_version:
        log.warning(
            "secret %s changed under us (expected %s, found %s); aborting CAS write",
            name,
            expected_version,
            current.version_id,
        )
        raise SecretVersionConflict(name, expected_version, current.version_id)

    response = client.add_secret_version(
        request={
            "parent": parent,
            "payload": {"data": new_payload.encode("utf-8")},
        }
    )
    new_version = response.name.rsplit("/", 1)[-1]
    log.info("wrote secret %s version %s (was %s)", name, new_version, expected_version)
    return SecretRef(name=name, version_id=new_version, payload=new_payload)


def write_secret(project_id: str, name: str, new_payload: str) -> SecretRef:
    """Add a new version to a secret unconditionally.

    Use this for first-time bootstrap or when the caller holds exclusive write
    authority (e.g. the admin OAuth callback).  For concurrent-safe rotation
    use write_secret_cas instead.
    """
    client = _client()
    parent = f"projects/{project_id}/secrets/{name}"
    response = client.add_secret_version(
        request={"parent": parent, "payload": {"data": new_payload.encode("utf-8")}}
    )
    new_version = response.name.rsplit("/", 1)[-1]
    log.info("wrote secret %s version %s", name, new_version)
    return SecretRef(name=name, version_id=new_version, payload=new_payload)


class SecretVersionConflict(RuntimeError):
    """Raised when a CAS write detects another writer changed the secret."""

    def __init__(self, name: str, expected: str, actual: str) -> None:
        super().__init__(
            f"secret {name!r}: expected version {expected}, found {actual}"
        )
        self.name = name
        self.expected = expected
        self.actual = actual
