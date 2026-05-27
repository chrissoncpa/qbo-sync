"""Runtime configuration.

Configuration sources, in order of precedence:
1. Environment variables (set on Cloud Run as --set-env-vars at deploy time).
2. Secret Manager (resolved lazily; see src.utils.secrets).

Non-secret values: GCP_PROJECT_ID, ENVIRONMENT, WORKBOOK_ID, DRIVE_*_ID,
                   ALLOWED_INVOKER_EMAIL, OAUTH_REDIRECT_URI, FLASK_SECRET_KEY,
                   MULTI_TENANT, ADMIN_API_KEY.
Secret values: QBO_CLIENT_ID, QBO_CLIENT_SECRET, QBO_REFRESH_TOKEN, QBO_REALM_ID.

The is_cloud_run flag is set by Cloud Run automatically (K_SERVICE env var).
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    project_id: str
    environment: str  # "sandbox" | "production"
    workbook_id: str
    drive_inbox_folder_id: str
    drive_archive_root_id: str
    allowed_invoker_email: str
    is_cloud_run: bool
    oauth_redirect_uri: str
    flask_secret_key: str
    multi_tenant: bool = False
    admin_api_key: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            project_id=_required("GCP_PROJECT_ID"),
            environment=os.environ.get("ENVIRONMENT", "sandbox"),
            workbook_id=os.environ.get("WORKBOOK_ID", ""),
            drive_inbox_folder_id=os.environ.get("DRIVE_INBOX_FOLDER_ID", ""),
            drive_archive_root_id=os.environ.get("DRIVE_ARCHIVE_ROOT_ID", ""),
            allowed_invoker_email=os.environ.get("ALLOWED_INVOKER_EMAIL", ""),
            is_cloud_run=bool(os.environ.get("K_SERVICE")),
            oauth_redirect_uri=os.environ.get("OAUTH_REDIRECT_URI", ""),
            # If not set, generate a random key; sessions won't survive restarts
            # but that's fine for the one-shot OAuth bootstrap flow.
            flask_secret_key=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
            multi_tenant=os.environ.get("MULTI_TENANT", "").lower() in ("1", "true", "yes"),
            admin_api_key=os.environ.get("ADMIN_API_KEY", ""),
        )

    @property
    def is_sandbox(self) -> bool:
        return self.environment.lower() == "sandbox"

    @property
    def secret_suffix(self) -> str:
        """Suffix used to disambiguate Secret Manager keys per environment."""
        return self.environment.lower()

    @property
    def credential_suffix(self) -> str:
        """Suffix for client_id / client_secret secrets (same as secret_suffix in single-tenant)."""
        return self.secret_suffix


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        # Fail loudly at boot rather than mysteriously at first use.
        raise RuntimeError(f"Required env var {name!r} is not set")
    return val
