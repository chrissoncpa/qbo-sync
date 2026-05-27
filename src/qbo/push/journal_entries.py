"""Build and POST QBO JournalEntry objects from grouped Journal Entries sheet rows.

Each JE group produced by read_journal_entries has:
  _lines      list of line dicts (AccountName, PostingType, Amount, Description, ...)
  _sheet_rows list of 1-based sheet row numbers for status write-back
  _status_col 0-based column index of the Status cell
  RefNumber, TxnDate, Memo  shared header fields
"""

from __future__ import annotations

import logging
from typing import Any

from src.validators.common import ValidationError, resolve_entity, validate_currency, validate_required
from src.validators.balance import validate_journal_balance

log = logging.getLogger(__name__)


def push_journal_entry(group: dict[str, Any], ref_data: dict[str, list[list[str]]], qb: Any) -> Any:
    """Validate a JE group, build a JournalEntry, POST to QBO, and return the saved object."""
    from quickbooks.objects import JournalEntry
    from quickbooks.objects.journalentry import JournalEntryLine, JournalEntryLineDetail
    from quickbooks.objects.base import Ref

    lines_data = group.get("_lines", [])
    if len(lines_data) < 2:
        raise ValidationError("Journal entry must have at least 2 lines")

    if not group.get("TxnDate", "").strip():
        raise ValidationError("TxnDate is required")

    validate_journal_balance(lines_data)

    je = JournalEntry()
    je.TxnDate = group["TxnDate"]
    if group.get("RefNumber"):
        je.DocNumber = group["RefNumber"]
    if group.get("Memo"):
        je.PrivateNote = group["Memo"]

    qbo_lines = []
    for line_data in lines_data:
        if not line_data.get("AccountName", "").strip():
            raise ValidationError("AccountName is required on every Journal Entry line")

        amount = validate_currency(line_data["Amount"])
        posting = line_data.get("PostingType", "").strip().title()
        if posting not in ("Debit", "Credit"):
            raise ValidationError(
                f"PostingType must be Debit or Credit, got {line_data.get('PostingType')!r}"
            )

        acct_id = resolve_entity(
            line_data["AccountName"], ref_data["accounts"][1:], name_col_idx=2, id_col_idx=0
        )

        line = JournalEntryLine()
        line.Amount = amount
        if line_data.get("Description"):
            line.Description = line_data["Description"]

        detail = JournalEntryLineDetail()
        detail.PostingType = posting
        acct_ref = Ref()
        acct_ref.value = acct_id
        detail.AccountRef = acct_ref

        class_name = line_data.get("ClassLine", "").strip()
        if class_name:
            class_id = resolve_entity(
                class_name, ref_data["classes"][1:], name_col_idx=1, id_col_idx=0
            )
            cls_ref = Ref()
            cls_ref.value = class_id
            detail.ClassRef = cls_ref

        dept_name = line_data.get("LocationLine", "").strip()
        if dept_name:
            dept_id = resolve_entity(
                dept_name, ref_data["departments"][1:], name_col_idx=1, id_col_idx=0
            )
            dept_ref = Ref()
            dept_ref.value = dept_id
            detail.DepartmentRef = dept_ref

        line.JournalEntryLineDetail = detail
        qbo_lines.append(line)

    je.Line = qbo_lines

    saved = je.save(qb=qb)
    log.info("posted JournalEntry Id=%s DocNumber=%s lines=%d",
             saved.Id, je.DocNumber, len(qbo_lines))
    return saved
