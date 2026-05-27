"""Attach a Drive file to a freshly-posted QBO transaction.

Downloads the file from the Drive inbox, uploads it to QBO as an
Attachable linked to the transaction, then archives it to
Posted/YYYY/MM/ (or Failed/ on error).

Limits per file: 100 MB; types PDF/PNG/JPG/GIF/TIFF.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

log = logging.getLogger(__name__)

_MAX_BYTES = 100 * 1024 * 1024


def attach_file_to_transaction(
    filename: str,
    txn_id: str,
    txn_type: str,
    qb: Any,
    drive: Any,
    inbox_folder_id: str,
    archive_root_id: str,
) -> bool:
    """Find filename in Drive inbox, attach to QBO txn, archive file.

    Returns True if attachment succeeded, False if the file was not found
    (non-fatal). Raises on unexpected errors.

    txn_type is the QBO entity name, e.g. "Bill", "Invoice", "Purchase".
    """
    from quickbooks.objects import Attachable
    from quickbooks.objects.attachable import AttachableRef
    from quickbooks.objects.base import Ref

    file_id = drive.resolve_attachment(inbox_folder_id, filename)
    if file_id is None:
        return False

    content, mime_type, actual_name = drive.download_file(file_id)

    if len(content) > _MAX_BYTES:
        raise ValueError(
            f"Attachment {filename!r} is {len(content) // (1024 * 1024)} MB — exceeds QBO 100 MB limit"
        )

    attachable = Attachable()
    attachable.FileName = actual_name
    attachable.ContentType = mime_type
    attachable._FileBytes = content

    ref = AttachableRef()
    entity_ref = Ref()
    entity_ref.type = txn_type
    entity_ref.value = txn_id
    ref.EntityRef = entity_ref
    attachable.AttachableRef = [ref]

    attachable.save(qb=qb)

    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        drive.archive_to_posted(
            file_id,
            inbox_folder_id,
            archive_root_id,
            now.strftime("%Y"),
            now.strftime("%m"),
        )
    except Exception as exc:
        log.warning("archive failed for %r (attachment still succeeded): %s", filename, exc)

    log.info("attached %r to %s %s", filename, txn_type, txn_id)
    return True
