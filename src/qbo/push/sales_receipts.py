"""Build and POST QBO SalesReceipt objects from Sales Receipts sheet rows."""

from __future__ import annotations

import logging
from typing import Any

from src.validators.common import (
    resolve_entity, validate_currency,
    validate_exchange_rate, validate_required,
)

log = logging.getLogger(__name__)

_REQUIRED_FIELDS = ["TxnDate", "CustomerName", "ItemName", "Amount"]


def push_sales_receipt(row: dict[str, Any], ref_data: dict[str, list[list[str]]], qb: Any) -> Any:
    """Validate row, build a SalesReceipt, POST to QBO, and return the saved SalesReceipt."""
    from quickbooks.objects import SalesReceipt
    from quickbooks.objects.detailline import SalesItemLine, SalesItemLineDetail
    from quickbooks.objects.base import Ref

    validate_required(row, _REQUIRED_FIELDS)
    amount = validate_currency(row["Amount"])

    customer_id = resolve_entity(
        row["CustomerName"], ref_data["customers"][1:], name_col_idx=1, id_col_idx=0
    )
    item_id = resolve_entity(
        row["ItemName"], ref_data["items"][1:], name_col_idx=1, id_col_idx=0
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

    receipt = SalesReceipt()
    receipt.TxnDate = row["TxnDate"]
    if row.get("RefNumber"):
        receipt.DocNumber = row["RefNumber"]
    if row.get("Memo"):
        receipt.PrivateNote = row["Memo"]

    currency = row.get("Currency", "").strip()
    if currency:
        curr_ref = Ref()
        curr_ref.value = currency
        receipt.CurrencyRef = curr_ref
        rate = validate_exchange_rate(row.get("ExchangeRate", ""))
        if rate is not None:
            receipt.ExchangeRate = rate

    customer_ref = Ref()
    customer_ref.value = customer_id
    receipt.CustomerRef = customer_ref

    if row.get("DepositToAccount", "").strip():
        deposit_id = resolve_entity(
            row["DepositToAccount"], ref_data["accounts"][1:], name_col_idx=2, id_col_idx=0
        )
        deposit_ref = Ref()
        deposit_ref.value = deposit_id
        receipt.DepositToAccountRef = deposit_ref

    if dept_id:
        dept_ref = Ref()
        dept_ref.value = dept_id
        receipt.DepartmentRef = dept_ref

    line = SalesItemLine()
    line.Amount = amount
    if row.get("Description"):
        line.Description = row["Description"]

    detail = SalesItemLineDetail()
    item_ref = Ref()
    item_ref.value = item_id
    detail.ItemRef = item_ref
    if row.get("Quantity"):
        try:
            detail.Qty = float(row["Quantity"])
        except ValueError:
            pass
    if row.get("UnitPrice"):
        try:
            detail.UnitPrice = float(row["UnitPrice"])
        except ValueError:
            pass

    tax_code = row.get("TaxCode", "").strip()
    if tax_code:
        tc_ref = Ref()
        tc_ref.value = tax_code
        detail.TaxCodeRef = tc_ref

    if class_id:
        cls_ref = Ref()
        cls_ref.value = class_id
        detail.ClassRef = cls_ref

    line.SalesItemLineDetail = detail
    receipt.Line = [line]

    saved = receipt.save(qb=qb)
    log.info("posted SalesReceipt Id=%s DocNumber=%s Customer=%s Amount=%s",
             saved.Id, receipt.DocNumber, row["CustomerName"], amount)
    return saved
