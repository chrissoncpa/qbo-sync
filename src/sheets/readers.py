"""Per-tab row parsers — turn raw Sheets rows into typed dicts for validation and push.

Each reader returns a list of row dicts.  Every dict includes two metadata keys:
  _sheet_row   int   1-based Sheets row number (used for write-back)
  _status_col  int   0-based column index of the Status cell (used for write-back)

Rows whose Status cell is non-empty are excluded (idempotency gate).
"""

from __future__ import annotations

import logging
from typing import Any

from src.utils.idempotency import is_eligible_for_push

log = logging.getLogger(__name__)

# Full Bills column order (header + line + service) as built by build_workbook.py
BILLS_HEADERS = [
    "RefNumber", "TxnDate", "DueDate", "VendorName", "Currency", "ExchangeRate",
    "APAccount", "Class", "Location", "TermName", "Memo", "Attachment",
    "LineNum", "LineType", "AccountName", "ItemName", "Description",
    "Quantity", "UnitPrice", "Amount", "TaxCode",
    "ClassLine", "LocationLine", "CustomerName", "Billable", "AttachmentLine",
    "Status", "QBO ID", "Posted At",
]


def _cell(row: list[str], col_idx: int) -> str:
    """Return cell value or empty string if column is absent."""
    if col_idx < len(row):
        return str(row[col_idx]).strip()
    return ""


def _build_col_map(header_row: list[str]) -> dict[str, int]:
    return {name.strip(): idx for idx, name in enumerate(header_row)}


def read_bills(sheets: Any, workbook_id: str) -> list[dict[str, Any]]:
    """Read the Bills tab and return eligible rows as dicts.

    Eligible = Status cell is empty.  Skips the header row (row 1).
    Each dict includes _sheet_row and _status_col for write-back.
    """
    raw = sheets.read_tab(workbook_id, "Bills")
    if not raw:
        return []

    header = raw[0]
    col = _build_col_map(header)
    status_col = col.get("Status", len(BILLS_HEADERS) - 3)

    rows: list[dict[str, Any]] = []
    for sheet_row_idx, raw_row in enumerate(raw[1:], start=2):  # row 2 onwards
        status = _cell(raw_row, status_col)
        if not is_eligible_for_push(status):
            log.debug("bills row %d skipped (status=%r)", sheet_row_idx, status)
            continue

        rows.append({
            "RefNumber":    _cell(raw_row, col.get("RefNumber", 0)),
            "TxnDate":      _cell(raw_row, col.get("TxnDate", 1)),
            "DueDate":      _cell(raw_row, col.get("DueDate", 2)),
            "VendorName":   _cell(raw_row, col.get("VendorName", 3)),
            "Currency":     _cell(raw_row, col.get("Currency", 4)),
            "ExchangeRate": _cell(raw_row, col.get("ExchangeRate", 5)),
            "APAccount":    _cell(raw_row, col.get("APAccount", 6)),
            "Class":        _cell(raw_row, col.get("Class", 7)),
            "Location":     _cell(raw_row, col.get("Location", 8)),
            "TermName":     _cell(raw_row, col.get("TermName", 9)),
            "Memo":         _cell(raw_row, col.get("Memo", 10)),
            "LineType":     _cell(raw_row, col.get("LineType", 13)),
            "AccountName":  _cell(raw_row, col.get("AccountName", 14)),
            "ItemName":     _cell(raw_row, col.get("ItemName", 15)),
            "Description":  _cell(raw_row, col.get("Description", 16)),
            "Quantity":     _cell(raw_row, col.get("Quantity", 17)),
            "UnitPrice":    _cell(raw_row, col.get("UnitPrice", 18)),
            "Amount":       _cell(raw_row, col.get("Amount", 19)),
            "TaxCode":      _cell(raw_row, col.get("TaxCode", 20)),
            "ClassLine":    _cell(raw_row, col.get("ClassLine", 21)),
            "LocationLine": _cell(raw_row, col.get("LocationLine", 22)),
            "CustomerName": _cell(raw_row, col.get("CustomerName", 23)),
            "Billable":     _cell(raw_row, col.get("Billable", 24)),
            "_sheet_row":   sheet_row_idx,
            "_status_col":  status_col,
        })

    log.info("read_bills: %d eligible rows from Bills tab", len(rows))
    return rows


INVOICES_HEADERS = [
    "RefNumber", "TxnDate", "DueDate", "CustomerName", "Currency", "ExchangeRate",
    "ARAccount", "Class", "Location", "TermName", "Memo", "Attachment",
    "LineNum", "LineType", "ItemName", "AccountName", "Description",
    "Quantity", "UnitPrice", "Amount", "TaxCode",
    "ClassLine", "LocationLine", "AttachmentLine",
    "Status", "QBO ID", "Posted At",
]

EXPENSES_HEADERS = [
    "RefNumber", "TxnDate", "PaymentType", "PaymentAccount", "VendorName",
    "Currency", "ExchangeRate", "Class", "Location", "Memo", "Attachment",
    "LineNum", "LineType", "AccountName", "ItemName", "Description",
    "Quantity", "UnitPrice", "Amount", "TaxCode",
    "ClassLine", "LocationLine", "CustomerName", "Billable", "AttachmentLine",
    "Status", "QBO ID", "Posted At",
]

SALES_RECEIPTS_HEADERS = [
    "RefNumber", "TxnDate", "CustomerName", "Currency", "ExchangeRate",
    "DepositToAccount", "Class", "Location", "Memo", "Attachment",
    "LineNum", "LineType", "ItemName", "AccountName", "Description",
    "Quantity", "UnitPrice", "Amount", "TaxCode",
    "ClassLine", "LocationLine", "AttachmentLine",
    "Status", "QBO ID", "Posted At",
]


def read_invoices(sheets: Any, workbook_id: str) -> list[dict[str, Any]]:
    raw = sheets.read_tab(workbook_id, "Invoices")
    if not raw:
        return []
    header = raw[0]
    col = _build_col_map(header)
    status_col = col.get("Status", len(INVOICES_HEADERS) - 3)
    rows: list[dict[str, Any]] = []
    for sheet_row_idx, raw_row in enumerate(raw[1:], start=2):
        status = _cell(raw_row, status_col)
        if not is_eligible_for_push(status):
            continue
        rows.append({
            "RefNumber":    _cell(raw_row, col.get("RefNumber", 0)),
            "TxnDate":      _cell(raw_row, col.get("TxnDate", 1)),
            "DueDate":      _cell(raw_row, col.get("DueDate", 2)),
            "CustomerName": _cell(raw_row, col.get("CustomerName", 3)),
            "Class":        _cell(raw_row, col.get("Class", 7)),
            "Location":     _cell(raw_row, col.get("Location", 8)),
            "Memo":         _cell(raw_row, col.get("Memo", 10)),
            "LineType":     _cell(raw_row, col.get("LineType", 13)),
            "ItemName":     _cell(raw_row, col.get("ItemName", 14)),
            "AccountName":  _cell(raw_row, col.get("AccountName", 15)),
            "Description":  _cell(raw_row, col.get("Description", 16)),
            "Quantity":     _cell(raw_row, col.get("Quantity", 17)),
            "UnitPrice":    _cell(raw_row, col.get("UnitPrice", 18)),
            "Amount":       _cell(raw_row, col.get("Amount", 19)),
            "ClassLine":    _cell(raw_row, col.get("ClassLine", 21)),
            "LocationLine": _cell(raw_row, col.get("LocationLine", 22)),
            "_sheet_row":   sheet_row_idx,
            "_status_col":  status_col,
        })
    log.info("read_invoices: %d eligible rows", len(rows))
    return rows


def read_expenses(sheets: Any, workbook_id: str) -> list[dict[str, Any]]:
    raw = sheets.read_tab(workbook_id, "Expenses")
    if not raw:
        return []
    header = raw[0]
    col = _build_col_map(header)
    status_col = col.get("Status", len(EXPENSES_HEADERS) - 3)
    rows: list[dict[str, Any]] = []
    for sheet_row_idx, raw_row in enumerate(raw[1:], start=2):
        status = _cell(raw_row, status_col)
        if not is_eligible_for_push(status):
            continue
        rows.append({
            "RefNumber":      _cell(raw_row, col.get("RefNumber", 0)),
            "TxnDate":        _cell(raw_row, col.get("TxnDate", 1)),
            "PaymentType":    _cell(raw_row, col.get("PaymentType", 2)),
            "PaymentAccount": _cell(raw_row, col.get("PaymentAccount", 3)),
            "VendorName":     _cell(raw_row, col.get("VendorName", 4)),
            "Class":          _cell(raw_row, col.get("Class", 7)),
            "Location":       _cell(raw_row, col.get("Location", 8)),
            "Memo":           _cell(raw_row, col.get("Memo", 9)),
            "LineType":       _cell(raw_row, col.get("LineType", 12)),
            "AccountName":    _cell(raw_row, col.get("AccountName", 13)),
            "Description":    _cell(raw_row, col.get("Description", 15)),
            "Quantity":       _cell(raw_row, col.get("Quantity", 16)),
            "UnitPrice":      _cell(raw_row, col.get("UnitPrice", 17)),
            "Amount":         _cell(raw_row, col.get("Amount", 18)),
            "ClassLine":      _cell(raw_row, col.get("ClassLine", 20)),
            "LocationLine":   _cell(raw_row, col.get("LocationLine", 21)),
            "CustomerName":   _cell(raw_row, col.get("CustomerName", 22)),
            "_sheet_row":     sheet_row_idx,
            "_status_col":    status_col,
        })
    log.info("read_expenses: %d eligible rows", len(rows))
    return rows


def read_sales_receipts(sheets: Any, workbook_id: str) -> list[dict[str, Any]]:
    raw = sheets.read_tab(workbook_id, "Sales Receipts")
    if not raw:
        return []
    header = raw[0]
    col = _build_col_map(header)
    status_col = col.get("Status", len(SALES_RECEIPTS_HEADERS) - 3)
    rows: list[dict[str, Any]] = []
    for sheet_row_idx, raw_row in enumerate(raw[1:], start=2):
        status = _cell(raw_row, status_col)
        if not is_eligible_for_push(status):
            continue
        rows.append({
            "RefNumber":        _cell(raw_row, col.get("RefNumber", 0)),
            "TxnDate":          _cell(raw_row, col.get("TxnDate", 1)),
            "CustomerName":     _cell(raw_row, col.get("CustomerName", 2)),
            "DepositToAccount": _cell(raw_row, col.get("DepositToAccount", 5)),
            "Class":            _cell(raw_row, col.get("Class", 6)),
            "Location":         _cell(raw_row, col.get("Location", 7)),
            "Memo":             _cell(raw_row, col.get("Memo", 8)),
            "LineType":         _cell(raw_row, col.get("LineType", 11)),
            "ItemName":         _cell(raw_row, col.get("ItemName", 12)),
            "AccountName":      _cell(raw_row, col.get("AccountName", 13)),
            "Description":      _cell(raw_row, col.get("Description", 14)),
            "Quantity":         _cell(raw_row, col.get("Quantity", 15)),
            "UnitPrice":        _cell(raw_row, col.get("UnitPrice", 16)),
            "Amount":           _cell(raw_row, col.get("Amount", 17)),
            "ClassLine":        _cell(raw_row, col.get("ClassLine", 19)),
            "LocationLine":     _cell(raw_row, col.get("LocationLine", 20)),
            "_sheet_row":       sheet_row_idx,
            "_status_col":      status_col,
        })
    log.info("read_sales_receipts: %d eligible rows", len(rows))
    return rows


DEPOSITS_HEADERS = [
    "RefNumber", "TxnDate", "DepositToAccount", "Memo", "Class", "Location", "Attachment",
    "LineNum", "AccountName", "Description", "Amount", "TaxCode",
    "ClassLine", "LocationLine", "AttachmentLine",
    "Status", "QBO ID", "Posted At",
]

JOURNAL_ENTRIES_HEADERS = [
    "RefNumber", "TxnDate", "Memo",
    "LineNum", "AccountName", "PostingType", "Amount", "Description",
    "ClassLine", "LocationLine", "EntityName", "EntityType",
    "Status", "QBO ID", "Posted At",
]


def read_deposits(sheets: Any, workbook_id: str) -> list[dict[str, Any]]:
    raw = sheets.read_tab(workbook_id, "Deposits")
    if not raw:
        return []
    header = raw[0]
    col = _build_col_map(header)
    status_col = col.get("Status", len(DEPOSITS_HEADERS) - 3)
    rows: list[dict[str, Any]] = []
    for sheet_row_idx, raw_row in enumerate(raw[1:], start=2):
        status = _cell(raw_row, status_col)
        if not is_eligible_for_push(status):
            continue
        rows.append({
            "RefNumber":        _cell(raw_row, col.get("RefNumber", 0)),
            "TxnDate":          _cell(raw_row, col.get("TxnDate", 1)),
            "DepositToAccount": _cell(raw_row, col.get("DepositToAccount", 2)),
            "Memo":             _cell(raw_row, col.get("Memo", 3)),
            "Class":            _cell(raw_row, col.get("Class", 4)),
            "Location":         _cell(raw_row, col.get("Location", 5)),
            "AccountName":      _cell(raw_row, col.get("AccountName", 8)),
            "Description":      _cell(raw_row, col.get("Description", 9)),
            "Amount":           _cell(raw_row, col.get("Amount", 10)),
            "ClassLine":        _cell(raw_row, col.get("ClassLine", 12)),
            "LocationLine":     _cell(raw_row, col.get("LocationLine", 13)),
            "_sheet_row":       sheet_row_idx,
            "_status_col":      status_col,
        })
    log.info("read_deposits: %d eligible rows", len(rows))
    return rows


def read_journal_entries(sheets: Any, workbook_id: str) -> list[dict[str, Any]]:
    """Read Journal Entries tab and return one group dict per unique RefNumber.

    Each group has:
      RefNumber, TxnDate, Memo  — shared header fields
      _lines      list of per-line dicts
      _sheet_rows list of 1-based row numbers (for multi-row status write-back)
      _status_col 0-based status column index
    """
    from collections import OrderedDict

    raw = sheets.read_tab(workbook_id, "Journal Entries")
    if not raw:
        return []
    header = raw[0]
    col = _build_col_map(header)
    status_col = col.get("Status", len(JOURNAL_ENTRIES_HEADERS) - 3)

    groups: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for sheet_row_idx, raw_row in enumerate(raw[1:], start=2):
        status = _cell(raw_row, status_col)
        if not is_eligible_for_push(status):
            continue
        ref = _cell(raw_row, col.get("RefNumber", 0))
        key = ref if ref else f"__row_{sheet_row_idx}"
        if key not in groups:
            groups[key] = {
                "RefNumber":   ref,
                "TxnDate":     _cell(raw_row, col.get("TxnDate", 1)),
                "Memo":        _cell(raw_row, col.get("Memo", 2)),
                "_sheet_rows": [],
                "_status_col": status_col,
                "_lines":      [],
            }
        groups[key]["_sheet_rows"].append(sheet_row_idx)
        groups[key]["_lines"].append({
            "AccountName": _cell(raw_row, col.get("AccountName", 4)),
            "PostingType": _cell(raw_row, col.get("PostingType", 5)),
            "Amount":      _cell(raw_row, col.get("Amount", 6)),
            "Description": _cell(raw_row, col.get("Description", 7)),
            "ClassLine":   _cell(raw_row, col.get("ClassLine", 8)),
            "LocationLine":_cell(raw_row, col.get("LocationLine", 9)),
        })

    result = list(groups.values())
    log.info("read_journal_entries: %d eligible groups", len(result))
    return result
