"""Build and POST QBO Purchase (Expense) objects from Expenses sheet rows."""

from __future__ import annotations

import logging
from typing import Any

from src.validators.common import (
    ValidationError, resolve_entity, validate_currency,
    validate_exchange_rate, validate_required,
)

log = logging.getLogger(__name__)

_REQUIRED_FIELDS = ["TxnDate", "PaymentAccount", "AccountName", "Amount"]
_VALID_PAYMENT_TYPES = {"Cash", "Check", "CreditCard"}


def push_expense(row: dict[str, Any], ref_data: dict[str, list[list[str]]], qb: Any) -> Any:
    """Validate row, build a Purchase, POST to QBO, and return the saved Purchase."""
    from quickbooks.objects import Purchase
    from quickbooks.objects.detailline import AccountBasedExpenseLine, AccountBasedExpenseLineDetail
    from quickbooks.objects.base import Ref

    validate_required(row, _REQUIRED_FIELDS)

    payment_type = row.get("PaymentType", "Cash").strip()
    if payment_type not in _VALID_PAYMENT_TYPES:
        raise ValidationError(
            f"PaymentType must be one of {sorted(_VALID_PAYMENT_TYPES)}, got {payment_type!r}"
        )

    amount = validate_currency(row["Amount"])

    payment_account_id = resolve_entity(
        row["PaymentAccount"], ref_data["accounts"][1:], name_col_idx=2, id_col_idx=0
    )
    expense_account_id = resolve_entity(
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

    purchase = Purchase()
    purchase.PaymentType = payment_type
    purchase.TxnDate = row["TxnDate"]
    if row.get("RefNumber"):
        purchase.DocNumber = row["RefNumber"]
    if row.get("Memo"):
        purchase.PrivateNote = row["Memo"]

    currency = row.get("Currency", "").strip()
    if currency:
        curr_ref = Ref()
        curr_ref.value = currency
        purchase.CurrencyRef = curr_ref
        rate = validate_exchange_rate(row.get("ExchangeRate", ""))
        if rate is not None:
            purchase.ExchangeRate = rate

    acct_ref = Ref()
    acct_ref.value = payment_account_id
    purchase.AccountRef = acct_ref

    if row.get("VendorName", "").strip():
        vendor_id = resolve_entity(
            row["VendorName"], ref_data["vendors"][1:], name_col_idx=1, id_col_idx=0
        )
        entity_ref = Ref()
        entity_ref.value = vendor_id
        entity_ref.type = "Vendor"
        purchase.EntityRef = entity_ref

    if dept_id:
        dept_ref = Ref()
        dept_ref.value = dept_id
        purchase.DepartmentRef = dept_ref

    line = AccountBasedExpenseLine()
    line.Amount = amount
    if row.get("Description"):
        line.Description = row["Description"]

    detail = AccountBasedExpenseLineDetail()
    expense_ref = Ref()
    expense_ref.value = expense_account_id
    detail.AccountRef = expense_ref

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
    purchase.Line = [line]

    saved = purchase.save(qb=qb)
    log.info("posted Expense Id=%s DocNumber=%s PaymentType=%s Amount=%s",
             saved.Id, purchase.DocNumber, payment_type, amount)
    return saved
