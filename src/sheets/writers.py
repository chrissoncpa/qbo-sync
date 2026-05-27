"""Write Status / QBO ID / Posted At back to source rows; append batch summary to _Log.

write_row_status  — updates the three service columns on a single row
append_log        — appends a summary row to the _Log tab
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# _Log tab column order (matches build_workbook.py build_log_tab)
_LOG_HEADERS = ["Timestamp", "Action", "Sheet", "Rows", "Posted", "Errored", "Skipped", "Message"]


def _col_letter(col_idx: int) -> str:
    """Convert 0-based column index to Sheets A1 column letter (A, B, ..., Z, AA, ...)."""
    result = ""
    n = col_idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def write_row_status(
    sheets: Any,
    workbook_id: str,
    tab_name: str,
    sheet_row: int,
    status_col_idx: int,
    status: str,
    qbo_id: str = "",
    posted_at: str = "",
) -> None:
    """Write status, QBO ID, and posted_at into the three service columns of sheet_row.

    sheet_row is the 1-based Sheets row number.
    status_col_idx is the 0-based column index of the Status column.
    """
    start = _col_letter(status_col_idx)
    end = _col_letter(status_col_idx + 2)
    range_ = f"{tab_name}!{start}{sheet_row}:{end}{sheet_row}"
    sheets.write_range(workbook_id, range_, [[status, qbo_id, posted_at]])
    log.debug("wrote status %r to %s row %d", status, tab_name, sheet_row)


def append_log(
    sheets: Any,
    workbook_id: str,
    timestamp: str,
    action: str,
    sheet: str,
    rows: int,
    posted: int,
    errored: int,
    skipped: int,
    message: str = "",
) -> None:
    """Append one summary row to the _Log tab."""
    values = [[timestamp, action, sheet, rows, posted, errored, skipped, message]]
    # Append after the last row by using an open-ended range.
    sheets._svc.spreadsheets().values().append(
        spreadsheetId=workbook_id,
        range="_Log!A:H",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()
    log.debug("appended _Log row: action=%r sheet=%r posted=%d errored=%d", action, sheet, posted, errored)
