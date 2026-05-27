"""Build and POST QBO Invoice objects from Invoices sheet rows."""

from __future__ import annotations

import logging
from typing import Any

from src.validators.common import (
    resolve_entity, validate_currency,
    validate_exchange_rate, validate_required,
)

log = logging.getLogger(__name__)

_REQUIRED_FIELDS = ["TxnDate", "CustomerName", "ItemName", "Amount"]


def push_invoice(row: dict[str, Any], ref_data: dict[str, list[list[str]]], qb: Any) -> Any:
    """Validate row, build an Invoice, POST to QBO, and return the saved Invoice."""
    from quickbooks.objects import Invoice
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

    invoice = Invoice()
    invoice.TxnDate = row["TxnDate"]
    if row.get("DueDate"):
        invoice.DueDate = row["DueDate"]
    if row.get("RefNumber"):
        invoice.DocNumber = row["RefNumber"]
    if row.get("Memo"):
        invoice.PrivateNote = row["Memo"]

    currency = row.get("Currency", "").strip()
    if currency:
        curr_ref = Ref()
        curr_ref.value = currency
        invoice.CurrencyRef = curr_ref
        rate = validate_exchange_rate(row.get("ExchangeRate", ""))
        if rate is not None:
            invoice.ExchangeRate = rate

    ar_account = row.get("ARAccount", "").strip()
    if ar_account:
        ar_id = resolve_entity(ar_account, ref_data["accounts"][1:], name_col_idx=2, id_col_idx=0)
        ar_ref = Ref()
        ar_ref.value = ar_id
        invoice.ARAccountRef = ar_ref

    term_name = row.get("TermName", "").strip()
    if term_name and ref_data.get("terms", []):
        term_id = resolve_entity(term_name, ref_data["terms"][1:], name_col_idx=1, id_col_idx=0)
        term_ref = Ref()
        term_ref.value = term_id
        invoice.SalesTermRef = term_ref

    customer_ref = Ref()
    customer_ref.value = customer_id
    invoice.CustomerRef = customer_ref

    if dept_id:
        dept_ref = Ref()
        dept_ref.value = dept_id
        invoice.DepartmentRef = dept_ref

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
    invoice.Line = [line]

    saved = invoice.save(qb=qb)
    log.info("posted Invoice Id=%s DocNumber=%s Customer=%s Amount=%s",
             saved.Id, invoice.DocNumber, row["CustomerName"], amount)
    return saved
