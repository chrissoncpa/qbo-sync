"""Domain model dataclasses shared across modules."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field


@dataclass
class Company:
    """A tenant stored in Firestore."""

    id: str
    display_name: str
    workbook_id: str
    qbo_environment: str  # "sandbox" | "production"
    api_key_hash: str     # sha256 hex of the raw API key
    status: str           # "pending_oauth" | "active" | "suspended"
    created_at: datetime.datetime
    drive_inbox_folder_id: str = ""
    drive_archive_root_id: str = ""


@dataclass(frozen=True)
class CompanyContext:
    """Per-request config assembled from a Company record.

    Duck-types Config so all push/pull code works without modification.
    """

    project_id: str
    company_id: str
    workbook_id: str
    qbo_environment: str
    drive_inbox_folder_id: str
    drive_archive_root_id: str
    is_cloud_run: bool
    oauth_redirect_uri: str
    flask_secret_key: str

    # Duck-type Config properties ------------------------------------------------

    @property
    def environment(self) -> str:
        return self.qbo_environment.lower()

    @property
    def is_sandbox(self) -> bool:
        return self.qbo_environment.lower() == "sandbox"

    @property
    def secret_suffix(self) -> str:
        """Per-company suffix — used for refresh_token and realm_id secrets."""
        return self.company_id

    @property
    def credential_suffix(self) -> str:
        """Shared suffix — used for client_id and client_secret secrets."""
        return self.qbo_environment.lower()

    @property
    def allowed_invoker_email(self) -> str:
        # Multi-tenant auth uses X-Api-Key; OIDC check is skipped.
        return ""

    @property
    def is_multi_tenant(self) -> bool:
        return True
