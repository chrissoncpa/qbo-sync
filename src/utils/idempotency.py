"""Status-column gate: only rows whose Status cell is empty are eligible to push.

Rules:
  - Empty / None / whitespace-only → eligible
  - "posted"                        → skip (already in QBO)
  - "error: ..."                    → skip until the user clears the cell to retry
"""

from __future__ import annotations


def is_eligible_for_push(status: str | None) -> bool:
    """Return True if the row should be sent to QBO."""
    return not status or not status.strip()
