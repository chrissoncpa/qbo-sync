"""Google Drive API wrapper for attachment management.

Operations:
  resolve_attachment  — find a file by name in the inbox folder
  download_file       — return (bytes, mime_type, filename)
  archive_to_posted   — move file to archive_root/Posted/YYYY/MM/
  move_to_failed      — move file to archive_root/Failed/
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveClient:
    def __init__(self, service: Any) -> None:
        self._svc = service

    @classmethod
    def from_credentials(cls) -> "DriveClient":
        from google.auth import default
        from googleapiclient.discovery import build

        creds, _ = default(scopes=_SCOPES)
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return cls(service)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def resolve_attachment(self, folder_id: str, filename: str) -> str | None:
        """Return the Drive file ID for filename inside folder_id, or None."""
        safe_name = filename.replace("'", "\\'")
        query = f"'{folder_id}' in parents and name = '{safe_name}' and trashed = false"
        result = (
            self._svc.files()
            .list(q=query, fields="files(id,name,mimeType)", pageSize=1)
            .execute()
        )
        files = result.get("files", [])
        if not files:
            log.warning("attachment %r not found in Drive folder %s", filename, folder_id)
            return None
        return files[0]["id"]

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_file(self, file_id: str) -> tuple[bytes, str, str]:
        """Return (content_bytes, mime_type, filename)."""
        meta = (
            self._svc.files()
            .get(fileId=file_id, fields="mimeType,name")
            .execute()
        )
        content: bytes = (
            self._svc.files()
            .get_media(fileId=file_id)
            .execute()
        )
        return content, meta["mimeType"], meta["name"]

    # ------------------------------------------------------------------
    # Archive
    # ------------------------------------------------------------------

    def archive_to_posted(
        self,
        file_id: str,
        inbox_folder_id: str,
        archive_root_id: str,
        yyyy: str,
        mm: str,
    ) -> None:
        """Move file to archive_root/Posted/YYYY/MM/, creating folders as needed."""
        posted_id = self._ensure_folder(archive_root_id, "Posted")
        year_id = self._ensure_folder(posted_id, yyyy)
        month_id = self._ensure_folder(year_id, mm)
        self._move_file(file_id, inbox_folder_id, month_id)
        log.debug("archived %s to Posted/%s/%s", file_id, yyyy, mm)

    def move_to_failed(
        self,
        file_id: str,
        inbox_folder_id: str,
        archive_root_id: str,
    ) -> None:
        """Move file to archive_root/Failed/, creating the folder as needed."""
        failed_id = self._ensure_folder(archive_root_id, "Failed")
        self._move_file(file_id, inbox_folder_id, failed_id)
        log.debug("moved %s to Failed/", file_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_folder(self, parent_id: str, name: str) -> str:
        """Return the ID of name inside parent_id, creating it if absent."""
        safe_name = name.replace("'", "\\'")
        query = (
            f"'{parent_id}' in parents and name = '{safe_name}' "
            f"and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        result = (
            self._svc.files()
            .list(q=query, fields="files(id)", pageSize=1)
            .execute()
        )
        files = result.get("files", [])
        if files:
            return files[0]["id"]
        folder = (
            self._svc.files()
            .create(
                body={
                    "name": name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent_id],
                },
                fields="id",
            )
            .execute()
        )
        log.info("created Drive folder %r under %s", name, parent_id)
        return folder["id"]

    def _move_file(self, file_id: str, from_folder_id: str, to_folder_id: str) -> None:
        self._svc.files().update(
            fileId=file_id,
            addParents=to_folder_id,
            removeParents=from_folder_id,
            fields="id,parents",
        ).execute()
