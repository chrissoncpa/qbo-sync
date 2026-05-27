"""Build and POST QBO Deposit objects from Deposits sheet rows."""

from __future__ import annotations

import logging
from typing import Any

from src.validators.common import (
    resolve_entity, validate_currency,
    validate_exchange_rate, validate_required,
)

log = logging.getLogger(__name__)

_REQUIRED_FIELDS = ["TxnDate", "DepositToAccount", "AccountName", "Amount"]


def push_deposit(row: dict[str, Any], ref_data: dict[str, list[list[str]]], qb: Any) -> Any:
    """Validate row, build a Deposit, POST to QBO, and return the saved Deposit."""
    from quickbooks.objects import Deposit
    from quickbooks.objects.deposit import DepositLine, DepositLineDetail
    from quickbooks.objects.base import Ref

    validate_required(row, _REQUIRED_FIELDS)
    amount = validate_currency(row["Amount"])

    deposit_acct_id = resolve_entity(
        row["DepositToAccount"], ref_data["accounts"][1:], name_col_idx=2, id_col_idx=0
    )
    line_acct_id = resolve_entity(
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

    deposit = Deposit()
    deposit.TxnDate = row["TxnDate"]
    if row.get("RefNumber"):
        deposit.DocNumber = row["RefNumber"]
    if row.get("Memo"):
        deposit.PrivateNote = row["Memo"]

    currency = row.get("Currency", "").strip()
    if currency:
        curr_ref = Ref()
        curr_ref.value = currency
        deposit.CurrencyRef = curr_ref
        rate = validate_exchange_rate(row.get("ExchangeRate", ""))
        if rate is not None:
            deposit.ExchangeRate = rate

    acct_ref = Ref()
    acct_ref.value = deposit_acct_id
    deposit.DepositToAccountRef = acct_ref

    if dept_id:
        dept_ref = Ref()
        dept_ref.value = dept_id
        deposit.DepartmentRef = dept_ref

    line = DepositLine()
    line.Amount = amount
    if row.get("Description"):
        line.Description = row["Description"]

    detail = DepositLineDetail()
    line_ref = Ref()
    line_ref.value = line_acct_id
    detail.AccountRef = line_ref

    if class_id:
        cls_ref = Ref()
        cls_ref.value = class_id
        detail.ClassRef = cls_ref

    line.DepositLineDetail = detail
    deposit.Line = [line]

    saved = deposit.save(qb=qb)
    log.info("posted Deposit Id=%s DocNumber=%s DepositTo=%s Amount=%s",
             saved.Id, deposit.DocNumber, row["DepositToAccount"], amount)
    return saved
