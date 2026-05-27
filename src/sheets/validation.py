"""Generate Sheets API DataValidation rules pointing at the _ reference tabs.

After every /pull the reference tabs are refreshed; this module then scans
each transaction tab's header row and applies ONE_OF_RANGE dropdowns to any
column whose name appears in _VALIDATION_MAP.

Supported column names → (reference tab, column letter):
  Account / AccountRef  → _Accounts  col C (FullyQualifiedName)
  Vendor  / VendorRef   → _Vendors   col B (DisplayName)
  Customer/ CustomerRef → _Customers col B (DisplayName)
  Class   / ClassRef    → _Classes   col B (Name)
  Department/ Location  → _Departments col B (Name)
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Transaction tabs that contain reference columns.
_TRANSACTION_TABS = [
    "Bills",
    "Invoices",
    "Expenses",
    "Sales Receipts",
    "Deposits",
    "Journal Entries",
]

# Maps a header cell value → (reference tab name, column letter in that tab).
_VALIDATION_MAP: dict[str, tuple[str, str]] = {
    "Account":       ("_Accounts",   "C"),  # FullyQualifiedName
    "AccountRef":    ("_Accounts",   "C"),
    "Vendor":        ("_Vendors",    "B"),  # DisplayName
    "VendorRef":     ("_Vendors",    "B"),
    "Customer":      ("_Customers",  "B"),  # DisplayName
    "CustomerRef":   ("_Customers",  "B"),
    "Class":         ("_Classes",    "B"),  # Name
    "ClassRef":      ("_Classes",    "B"),
    "Department":    ("_Departments","B"),  # Name
    "DepartmentRef": ("_Departments","B"),
    "Location":      ("_Departments","B"),
    "VendorName":    ("_Vendors",    "B"),
    "AccountName":   ("_Accounts",   "C"),
    "CustomerName":  ("_Customers",  "B"),
    "ClassLine":     ("_Classes",    "B"),
    "LocationLine":  ("_Departments","B"),
    "ItemName":      ("_Items",      "B"),
    "PaymentAccount":  ("_Accounts",   "C"),
    "DepositToAccount":("_Accounts",   "C"),
    "TermName":        ("_Terms",       "B"),
}

# Reference data goes up to row 1001 (header + 1000 items).
_REF_MAX_ROW = 1001
# Transaction data starts at row 2 (row 1 is the header) and can go to 10001.
_TXN_MAX_ROW = 10001


def refresh_validation_rules(cfg: Any, sheets: Any) -> int:
    """Scan transaction tabs and apply dropdown validation rules.

    Reads spreadsheet metadata to get numeric sheetIds, then for every
    transaction tab that exists in the workbook, reads its header row and
    applies a ONE_OF_RANGE rule to each column whose name is in _VALIDATION_MAP.

    Returns the total number of rules applied.
    """
    sheet_id_map = _get_sheet_id_map(sheets, cfg.workbook_id)

    requests: list[dict[str, Any]] = []
    for tab_name in _TRANSACTION_TABS:
        sheet_id = sheet_id_map.get(tab_name)
        if sheet_id is None:
            log.debug("tab %r not in workbook — skipping validation", tab_name)
            continue

        header_rows = sheets.read_tab(cfg.workbook_id, f"{tab_name}!1:1")
        if not header_rows:
            continue
        headers = header_rows[0]

        for col_idx, header in enumerate(headers):
            spec = _VALIDATION_MAP.get(header)
            if spec is None:
                continue
            ref_tab, ref_col = spec
            requests.append(
                _make_validation_request(sheet_id, col_idx, ref_tab, ref_col)
            )

    if requests:
        sheets.batch_update(cfg.workbook_id, requests)

    log.info("applied %d dropdown validation rules across transaction tabs", len(requests))
    return len(requests)


def _get_sheet_id_map(sheets: Any, workbook_id: str) -> dict[str, int]:
    metadata = (
        sheets._svc.spreadsheets()
        .get(spreadsheetId=workbook_id, fields="sheets.properties")
        .execute()
    )
    return {
        s["properties"]["title"]: s["properties"]["sheetId"]
        for s in metadata.get("sheets", [])
    }


def _make_validation_request(
    sheet_id: int,
    col_idx: int,
    ref_tab: str,
    ref_col: str,
) -> dict[str, Any]:
    return {
        "setDataValidation": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "endRowIndex": _TXN_MAX_ROW,
                "startColumnIndex": col_idx,
                "endColumnIndex": col_idx + 1,
            },
            "rule": {
                "condition": {
                    "type": "ONE_OF_RANGE",
                    "values": [
                        {
                            "userEnteredValue": (
                                f"='{ref_tab}'!${ref_col}$2:${ref_col}${_REF_MAX_ROW}"
                            )
                        }
                    ],
                },
                "showCustomUi": True,
                "strict": False,
            },
        }
    }
