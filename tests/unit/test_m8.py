"""Unit tests for M8: DriveClient, attach_file_to_transaction, /push attachment wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# DriveClient.resolve_attachment
# ---------------------------------------------------------------------------

class TestResolveAttachment:
    def _client(self, files):
        from src.drive.client import DriveClient
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {"files": files}
        return DriveClient(svc)

    def test_returns_file_id_when_found(self):
        client = self._client([{"id": "F1", "name": "receipt.pdf", "mimeType": "application/pdf"}])
        assert client.resolve_attachment("FOLDER", "receipt.pdf") == "F1"

    def test_returns_none_when_not_found(self):
        client = self._client([])
        assert client.resolve_attachment("FOLDER", "missing.pdf") is None


# ---------------------------------------------------------------------------
# DriveClient.download_file
# ---------------------------------------------------------------------------

class TestDownloadFile:
    def test_returns_content_mime_name(self):
        from src.drive.client import DriveClient
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = {
            "mimeType": "application/pdf", "name": "receipt.pdf"
        }
        svc.files.return_value.get_media.return_value.execute.return_value = b"PDF-CONTENT"
        client = DriveClient(svc)
        content, mime, name = client.download_file("F1")
        assert content == b"PDF-CONTENT"
        assert mime == "application/pdf"
        assert name == "receipt.pdf"


# ---------------------------------------------------------------------------
# DriveClient.archive_to_posted
# ---------------------------------------------------------------------------

class TestArchiveToPosted:
    def _client(self):
        from src.drive.client import DriveClient
        svc = MagicMock()
        # _ensure_folder: list returns nothing (folder doesn't exist), create returns id
        svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        svc.files.return_value.create.return_value.execute.side_effect = [
            {"id": "POSTED_ID"},
            {"id": "YEAR_ID"},
            {"id": "MONTH_ID"},
        ]
        svc.files.return_value.update.return_value.execute.return_value = {}
        return DriveClient(svc)

    def test_creates_folder_hierarchy_and_moves(self):
        client = self._client()
        client.archive_to_posted("F1", "INBOX", "ARCHIVE_ROOT", "2024", "03")
        # update (move) should be called once
        client._svc.files.return_value.update.assert_called_once()


# ---------------------------------------------------------------------------
# attach_file_to_transaction
# ---------------------------------------------------------------------------

class TestAttachFileToTransaction:
    def _drive(self, file_id="F1", content=b"bytes", mime="application/pdf", name="receipt.pdf"):
        drive = MagicMock()
        drive.resolve_attachment.return_value = file_id
        drive.download_file.return_value = (content, mime, name)
        return drive

    def test_returns_true_on_success(self):
        from src.qbo.attach import attach_file_to_transaction
        drive = self._drive()
        mock_saved = MagicMock()
        with patch("quickbooks.objects.Attachable") as MockAtt:
            instance = MagicMock()
            instance.save.return_value = mock_saved
            MockAtt.return_value = instance
            result = attach_file_to_transaction(
                "receipt.pdf", "BILL-1", "Bill",
                MagicMock(), drive, "INBOX", "ARCHIVE"
            )
        assert result is True

    def test_returns_false_when_file_not_found(self):
        from src.qbo.attach import attach_file_to_transaction
        drive = MagicMock()
        drive.resolve_attachment.return_value = None
        result = attach_file_to_transaction(
            "missing.pdf", "BILL-1", "Bill",
            MagicMock(), drive, "INBOX", "ARCHIVE"
        )
        assert result is False

    def test_raises_when_file_too_large(self):
        from src.qbo.attach import attach_file_to_transaction
        drive = self._drive(content=b"x" * (101 * 1024 * 1024))
        with pytest.raises(ValueError, match="100 MB"):
            attach_file_to_transaction(
                "big.pdf", "BILL-1", "Bill",
                MagicMock(), drive, "INBOX", "ARCHIVE"
            )

    def test_sets_file_bytes_on_attachable(self):
        from src.qbo.attach import attach_file_to_transaction
        drive = self._drive(content=b"PDF", mime="application/pdf", name="r.pdf")
        with patch("quickbooks.objects.Attachable") as MockAtt:
            instance = MagicMock()
            instance.save.return_value = MagicMock()
            MockAtt.return_value = instance
            attach_file_to_transaction(
                "r.pdf", "BILL-1", "Bill",
                MagicMock(), drive, "INBOX", "ARCHIVE"
            )
            assert instance._FileBytes == b"PDF"


# ---------------------------------------------------------------------------
# /push route: attachment wiring
# ---------------------------------------------------------------------------

class TestPushRouteAttachment:
    def test_attach_called_when_drive_configured_and_attachment_present(self):
        from src.app import create_app
        from src.config import Config

        cfg = Config(
            project_id="YOUR_GCP_PROJECT_ID",
            environment="sandbox",
            workbook_id="WB123",
            drive_inbox_folder_id="INBOX",
            drive_archive_root_id="ARCHIVE",
            allowed_invoker_email="",
            is_cloud_run=False,
            oauth_redirect_uri="https://example.com/oauth/callback",
            flask_secret_key="test",
        )
        app = create_app(cfg)
        app.config["TESTING"] = True

        mock_saved_bill = MagicMock()
        mock_saved_bill.Id = "BILL-99"

        row = {
            "TxnDate": "2024-01-15", "VendorName": "ACME Corp",
            "AccountName": "Office Expenses", "Amount": "100.00",
            "RefNumber": "", "DueDate": "", "Memo": "", "LineType": "",
            "Description": "", "Class": "", "ClassLine": "",
            "Location": "", "LocationLine": "", "Attachment": "receipt.pdf",
            "_sheet_row": 2, "_status_col": 26,
        }

        with (
            patch("src.qbo.client.fetch_secret"),
            patch("src.qbo.client.write_secret_cas"),
            patch("intuitlib.client.AuthClient"),
            patch("quickbooks.QuickBooks"),
            patch("src.sheets.client.SheetsClient.from_credentials", return_value=MagicMock(
                read_tab=MagicMock(return_value=[]),
                write_range=MagicMock(),
                _svc=MagicMock(**{"spreadsheets.return_value.values.return_value.append.return_value.execute.return_value": {}}),
            )),
            patch("src.sheets.readers.read_bills", return_value=[row]),
            patch("src.sheets.readers.read_invoices", return_value=[]),
            patch("src.sheets.readers.read_expenses", return_value=[]),
            patch("src.sheets.readers.read_sales_receipts", return_value=[]),
            patch("src.sheets.readers.read_deposits", return_value=[]),
            patch("src.sheets.readers.read_journal_entries", return_value=[]),
            patch("src.sheets.writers.append_log"),
            patch("src.sheets.writers.write_row_status"),
            patch("src.qbo.push.bills.push_bill", return_value=mock_saved_bill),
            patch("src.drive.client.DriveClient.from_credentials", return_value=MagicMock()),
            patch("src.qbo.attach.attach_file_to_transaction", return_value=True) as mock_attach,
        ):
            resp = app.test_client().post("/push")

        assert resp.status_code == 200
        mock_attach.assert_called_once_with(
            "receipt.pdf", "BILL-99", "Bill",
            ANY, ANY, "INBOX", "ARCHIVE"
        )

    def test_attach_skipped_when_no_drive_configured(self):
        from src.app import create_app
        from src.config import Config

        cfg = Config(
            project_id="YOUR_GCP_PROJECT_ID",
            environment="sandbox",
            workbook_id="WB123",
            drive_inbox_folder_id="",
            drive_archive_root_id="",
            allowed_invoker_email="",
            is_cloud_run=False,
            oauth_redirect_uri="https://example.com/oauth/callback",
            flask_secret_key="test",
        )
        app = create_app(cfg)
        app.config["TESTING"] = True

        with (
            patch("src.qbo.client.fetch_secret"),
            patch("src.qbo.client.write_secret_cas"),
            patch("intuitlib.client.AuthClient"),
            patch("quickbooks.QuickBooks"),
            patch("src.sheets.client.SheetsClient.from_credentials", return_value=MagicMock(
                read_tab=MagicMock(return_value=[]),
                write_range=MagicMock(),
                _svc=MagicMock(**{"spreadsheets.return_value.values.return_value.append.return_value.execute.return_value": {}}),
            )),
            patch("src.sheets.readers.read_bills", return_value=[]),
            patch("src.sheets.readers.read_invoices", return_value=[]),
            patch("src.sheets.readers.read_expenses", return_value=[]),
            patch("src.sheets.readers.read_sales_receipts", return_value=[]),
            patch("src.sheets.readers.read_deposits", return_value=[]),
            patch("src.sheets.readers.read_journal_entries", return_value=[]),
            patch("src.sheets.writers.append_log"),
            patch("src.drive.client.DriveClient.from_credentials") as mock_drive_cls,
        ):
            resp = app.test_client().post("/push")

        assert resp.status_code == 200
        mock_drive_cls.assert_not_called()


# Import ANY for the route test
from unittest.mock import ANY
