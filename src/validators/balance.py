"""Journal-entry balance validator: sum(Debit) == sum(Credit) within tolerance."""

from __future__ import annotations

from src.validators.common import ValidationError


def validate_journal_balance(lines: list[dict]) -> None:
    """Raise ValidationError if the JE lines are not balanced to within $0.01."""
    debits = credits = 0.0
    for line in lines:
        posting = line.get("PostingType", "").strip().title()
        try:
            amt = float(str(line.get("Amount", "0")).replace(",", ""))
        except ValueError:
            amt = 0.0
        if posting == "Debit":
            debits += amt
        elif posting == "Credit":
            credits += amt
        else:
            raise ValidationError(
                f"PostingType must be Debit or Credit, got {line.get('PostingType')!r}"
            )
    if round(abs(debits - credits), 2) > 0.01:
        raise ValidationError(
            f"Journal entry not balanced: debits={debits:.2f} credits={credits:.2f}"
        )
