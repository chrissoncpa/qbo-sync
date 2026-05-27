"""Generic per-row validators used across all push types.

validate_required  — assert named fields are non-empty
resolve_entity     — look up a display name in a reference tab and return its QBO Id
validate_currency  — parse an amount string into a float, reject non-numeric input
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class ValidationError(ValueError):
    """Raised when a row fails pre-push validation."""


def validate_required(row: dict[str, str], required_fields: list[str]) -> None:
    """Raise ValidationError if any field in required_fields is missing or blank."""
    missing = [f for f in required_fields if not row.get(f, "").strip()]
    if missing:
        raise ValidationError(f"required fields missing or blank: {', '.join(missing)}")


def resolve_entity(
    name: str,
    ref_rows: list[list[str]],
    name_col_idx: int,
    id_col_idx: int = 0,
) -> str:
    """Return the QBO Id for *name* from a reference tab's data rows.

    ref_rows should NOT include the header row (pass rows[1:]).
    Raises ValidationError if name is blank or not found.
    """
    name = name.strip()
    if not name:
        raise ValidationError("entity name is blank")
    for row in ref_rows:
        if len(row) > name_col_idx and row[name_col_idx].strip() == name:
            if len(row) > id_col_idx:
                return row[id_col_idx]
    raise ValidationError(f"entity {name!r} not found in reference tab")


def validate_currency(amount_str: str) -> float:
    """Parse amount_str into a float; raise ValidationError on bad input."""
    try:
        value = float(amount_str.replace(",", "").strip())
    except (ValueError, AttributeError):
        raise ValidationError(f"invalid amount: {amount_str!r}")
    if value < 0:
        raise ValidationError(f"amount must be non-negative, got {value}")
    return value


def validate_exchange_rate(value: str) -> float | None:
    """Parse exchange rate string; return float > 0 or None if blank."""
    if not value or not value.strip():
        return None
    try:
        rate = float(value.replace(",", "").strip())
    except (ValueError, AttributeError):
        raise ValidationError(f"ExchangeRate must be a number, got {value!r}")
    if rate <= 0:
        raise ValidationError(f"ExchangeRate must be positive, got {rate}")
    return rate
