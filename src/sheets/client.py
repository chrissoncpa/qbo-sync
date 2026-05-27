"""Google Sheets API wrapper.

Provides read/write helpers used by the pull and push pipelines.
Credentials come from Application Default Credentials (the qbo-bridge
service account on Cloud Run, or gcloud ADC locally).
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Sheets scope needed for both read and write.
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsClient:
    def __init__(self, service: Any) -> None:
        self._svc = service

    @classmethod
    def from_credentials(cls) -> "SheetsClient":
        from google.auth import default
        from googleapiclient.discovery import build

        creds, _ = default(scopes=_SCOPES)
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        return cls(service)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read_tab(self, workbook_id: str, tab_name: str) -> list[list[str]]:
        """Return all rows (including header) from the given tab as a 2-D list."""
        result = (
            self._svc.spreadsheets()
            .values()
            .get(spreadsheetId=workbook_id, range=tab_name)
            .execute()
        )
        return result.get("values", [])

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def _ensure_tab_exists(self, workbook_id: str, tab_name: str) -> None:
        """Create tab if it does not already exist in the spreadsheet."""
        meta = self._svc.spreadsheets().get(spreadsheetId=workbook_id).execute()
        existing = {s["properties"]["title"] for s in meta.get("sheets", [])}
        if tab_name not in existing:
            self.batch_update(workbook_id, [
                {"addSheet": {"properties": {"title": tab_name}}}
            ])
            log.info("created missing tab %r", tab_name)

    def write_reference_tab(
        self,
        workbook_id: str,
        tab_name: str,
        headers: list[str],
        rows: list[list[Any]],
    ) -> int:
        """Clear and rewrite a reference tab with a header row + data rows.

        Returns the number of data rows written.
        """
        self._ensure_tab_exists(workbook_id, tab_name)
        # Clear first so stale rows from a previous larger pull are removed.
        self._svc.spreadsheets().values().clear(
            spreadsheetId=workbook_id, range=tab_name
        ).execute()
        values: list[list[Any]] = [headers, *rows]
        self._svc.spreadsheets().values().update(
            spreadsheetId=workbook_id,
            range=f"{tab_name}!A1",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()
        log.debug("wrote %d rows to %s!A1", len(rows), tab_name)
        return len(rows)

    def write_range(
        self,
        workbook_id: str,
        range_: str,
        values: list[list[Any]],
    ) -> None:
        """Write arbitrary values to a named range."""
        self._svc.spreadsheets().values().update(
            spreadsheetId=workbook_id,
            range=range_,
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()

    def batch_update(self, workbook_id: str, requests: list[dict[str, Any]]) -> None:
        """Execute a batchUpdate (used for formatting, validation rules, etc.)."""
        self._svc.spreadsheets().batchUpdate(
            spreadsheetId=workbook_id,
            body={"requests": requests},
        ).execute()
