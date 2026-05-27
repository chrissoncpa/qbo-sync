"""Firestore-backed company registry for multi-tenant operation."""

from __future__ import annotations

import datetime
import hashlib
import logging

from src.models import Company

log = logging.getLogger(__name__)

_COLLECTION = "companies"


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _doc_to_company(doc_id: str, data: dict) -> Company:
    created_at = data.get("created_at")
    if hasattr(created_at, "ToDatetime"):
        created_at = created_at.ToDatetime(tzinfo=datetime.timezone.utc)
    elif not isinstance(created_at, datetime.datetime):
        created_at = datetime.datetime.now(datetime.timezone.utc)
    return Company(
        id=doc_id,
        display_name=data.get("display_name", ""),
        workbook_id=data.get("workbook_id", ""),
        qbo_environment=data.get("qbo_environment", "sandbox"),
        api_key_hash=data.get("api_key_hash", ""),
        status=data.get("status", "pending_oauth"),
        created_at=created_at,
        drive_inbox_folder_id=data.get("drive_inbox_folder_id", ""),
        drive_archive_root_id=data.get("drive_archive_root_id", ""),
    )


class CompanyStore:
    """CRUD operations on the Firestore `companies` collection."""

    def __init__(self, project_id: str) -> None:
        from google.cloud import firestore  # type: ignore[import-untyped]

        self._db = firestore.Client(project=project_id)

    def create(self, company: Company) -> None:
        doc = self._db.collection(_COLLECTION).document(company.id)
        doc.set(
            {
                "display_name": company.display_name,
                "workbook_id": company.workbook_id,
                "qbo_environment": company.qbo_environment,
                "api_key_hash": company.api_key_hash,
                "status": company.status,
                "created_at": company.created_at,
                "drive_inbox_folder_id": company.drive_inbox_folder_id,
                "drive_archive_root_id": company.drive_archive_root_id,
            }
        )
        log.info("company created: %s", company.id)

    def get(self, company_id: str) -> Company | None:
        snap = self._db.collection(_COLLECTION).document(company_id).get()
        if not snap.exists:
            return None
        return _doc_to_company(snap.id, snap.to_dict())  # type: ignore[arg-type]

    def get_by_api_key(self, raw_key: str) -> Company | None:
        hashed = _hash_key(raw_key)
        results = (
            self._db.collection(_COLLECTION)
            .where("api_key_hash", "==", hashed)
            .limit(1)
            .stream()
        )
        for snap in results:
            return _doc_to_company(snap.id, snap.to_dict())  # type: ignore[arg-type]
        return None

    def update_status(self, company_id: str, status: str) -> None:
        self._db.collection(_COLLECTION).document(company_id).update({"status": status})
        log.info("company %s status → %s", company_id, status)
