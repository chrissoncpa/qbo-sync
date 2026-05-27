"""Build and POST QBO Bill objects from Bills sheet rows.

Each row produces one Bill with one AccountBasedExpenseLine.  Item-based
lines (LineType = Item) are not yet supported — rows with LineType = Item
are rejected with a ValidationError until M6.

Entity names (VendorName, AccountName, ClassLine, LocationLine) are
resolved to QBO IDs using pre-loaded reference tab rows passed in via
ref_data.
"""

from __future__ import annotations

import logging
from typing import Any

from src.validators.common import (
    ValidationError, resolve_entity, validate_currency,
    validate_exchange_rate, validate_required,
)

log = logging.getLogger(__name__)

_REQUIRED_FIELDS = ["TxnDate", "VendorName", "AccountName", "Amount"]


def push_bill(row: dict[str, Any], ref_data: dict[str, list[list[str]]], qb: Any) -> Any:
    """Validate row, build a Bill, POST to QBO, and return the saved Bill.

    ref_data keys: "vendors", "accounts", "classes", "departments"
    Each value is the full tab rows (including header as row 0).

    Raises ValidationError for bad data; lets QBO/network errors propagate.
    """
    from quickbooks.objects import Bill
    from quickbooks.objects.detailline import AccountBasedExpenseLine, AccountBasedExpenseLineDetail
    from quickbooks.objects.base import Ref

    # -- Validate ----------------------------------------------------------------
    validate_required(row, _REQUIRED_FIELDS)

    if row.get("LineType", "").strip().lower() == "item":
        raise ValidationError("LineType=Item not yet supported; use LineType=Account")

    amount = validate_currency(row["Amount"])

    # -- Resolve entities --------------------------------------------------------
    vendor_id = resolve_entity(
        row["VendorName"], ref_data["vendors"][1:], name_col_idx=1, id_col_idx=0
    )
    account_id = resolve_entity(
        row["AccountName"], ref_data["accounts"][1:], name_col_idx=2, id_col_idx=0
    )

    class_id: str | None = None
    class_name = row.get("ClassLine") or row.get("Class", "")
    if class_name.strip():
        class_id = resolve_entity(
            class_name, ref_data["classes"][1:], name_col_idx=1, id_col_idx=0
        )

    dept_id: str | None = None
    dept_name = row.get("LocationLine") or row.get("Location", "")
    if dept_name.strip():
        dept_id = resolve_entity(
            dept_name, ref_data["departments"][1:], name_col_idx=1, id_col_idx=0
        )

    # -- Build Bill --------------------------------------------------------------
    bill = Bill()
    bill.TxnDate = row["TxnDate"]
    if row.get("DueDate"):
        bill.DueDate = row["DueDate"]
    if row.get("RefNumber"):
        bill.DocNumber = row["RefNumber"]
    if row.get("Memo"):
        bill.PrivateNote = row["Memo"]

    currency = row.get("Currency", "").strip()
    if currency:
        curr_ref = Ref()
        curr_ref.value = currency
        bill.CurrencyRef = curr_ref
        rate = validate_exchange_rate(row.get("ExchangeRate", ""))
        if rate is not None:
            bill.ExchangeRate = rate

    vendor_ref = Ref()
    vendor_ref.value = vendor_id
    bill.VendorRef = vendor_ref

    ap_account = row.get("APAccount", "").strip()
    if ap_account:
        ap_id = resolve_entity(ap_account, ref_data["accounts"][1:], name_col_idx=2, id_col_idx=0)
        ap_ref = Ref()
        ap_ref.value = ap_id
        bill.APAccountRef = ap_ref

    term_name = row.get("TermName", "").strip()
    if term_name and ref_data.get("terms", []):
        term_id = resolve_entity(term_name, ref_data["terms"][1:], name_col_idx=1, id_col_idx=0)
        term_ref = Ref()
        term_ref.value = term_id
        bill.SalesTermRef = term_ref

    if dept_id:
        dept_ref = Ref()
        dept_ref.value = dept_id
        bill.DepartmentRef = dept_ref

    # -- Build line item ---------------------------------------------------------
    line = AccountBasedExpenseLine()
    line.Amount = amount
    if row.get("Description"):
        line.Description = row["Description"]

    detail = AccountBasedExpenseLineDetail()
    acct_ref = Ref()
    acct_ref.value = account_id
    detail.AccountRef = acct_ref

    tax_code = row.get("TaxCode", "").strip()
    if tax_code:
        tc_ref = Ref()
        tc_ref.value = tax_code
        detail.TaxCodeRef = tc_ref

    if class_id:
        cls_ref = Ref()
        cls_ref.value = class_id
        detail.ClassRef = cls_ref

    line.AccountBasedExpenseLineDetail = detail
    bill.Line = [line]

    # -- POST to QBO -------------------------------------------------------------
    saved = bill.save(qb=qb)
    log.info("posted Bill Id=%s DocNumber=%s Vendor=%s Amount=%s", saved.Id, bill.DocNumber, row["VendorName"], amount)
    return saved
