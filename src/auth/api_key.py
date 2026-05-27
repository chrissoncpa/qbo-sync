"""Resolve an incoming X-Api-Key header to a CompanyContext."""

from __future__ import annotations

from src.config import Config
from src.db.companies import CompanyStore
from src.models import CompanyContext


def resolve_company_context(headers: dict, cfg: Config) -> CompanyContext | None:
    """Return a CompanyContext for the given API key, or None if invalid."""
    raw_key = headers.get("X-Api-Key", "")
    if not raw_key:
        return None
    store = CompanyStore(cfg.project_id)
    company = store.get_by_api_key(raw_key)
    if not company or company.status == "suspended":
        return None
    return CompanyContext(
        project_id=cfg.project_id,
        company_id=company.id,
        workbook_id=company.workbook_id,
        qbo_environment=company.qbo_environment,
        drive_inbox_folder_id=company.drive_inbox_folder_id,
        drive_archive_root_id=company.drive_archive_root_id,
        is_cloud_run=cfg.is_cloud_run,
        oauth_redirect_uri=cfg.oauth_redirect_uri,
        flask_secret_key=cfg.flask_secret_key,
    )
