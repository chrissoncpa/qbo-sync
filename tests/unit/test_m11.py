"""Unit tests for M11: /push row-selection filter."""

from __future__ import annotations

import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

from src.app import create_app
from src.config import Config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg() -> Config:
    return Config(
        project_id="YOUR_GCP_PROJECT_ID",
        environment="sandbox",
        workbook_id="WB123",
        drive_inbox_folder_id="",
        drive_archive_root_id="",
        allowed_invoker_email="",
        is_cloud_run=False,
        oauth_redirect_uri="https://example.com/callback",
        flask_secret_key="test",
    )


def _mock_sheets() -> MagicMock:
    sheets = MagicMock()
    sheets.read_tab.return_value = []
    (
        sheets._svc
        .spreadsheets.return_value
        .values.return_value
        .append.return_value
        .execute.return_value
    ) = {}
    return sheets


def _bill_row(sheet_row: int) -> dict:
    return {
        "RefNumber": f"B{sheet_row}", "TxnDate": "2024-01-15", "DueDate": "",
        "VendorName": "ACME Corp", "AccountName": "Office Expenses",
        "Amount": "100.00", "Description": "", "Class": "", "ClassLine": "",
        "Location": "", "LocationLine": "", "Memo": "", "LineType": "",
        "Currency": "", "ExchangeRate": "", "APAccount": "", "TermName": "",
        "TaxCode": "", "Attachment": "",
        "_sheet_row": sheet_row, "_status_col": 26,
    }


def _je_group(sheet_rows: list[int]) -> dict:
    return {
        "RefNumber": "JE-1", "TxnDate": "2024-01-15", "Memo": "",
        "_sheet_rows": sheet_rows, "_status_col": 12,
        "_lines": [
            {"AccountName": "Cash",    "PostingType": "Debit",  "Amount": "100",
             "Description": "", "ClassLine": "", "LocationLine": ""},
            {"AccountName": "Revenue", "PostingType": "Credit", "Amount": "100",
             "Description": "", "ClassLine": "", "LocationLine": ""},
        ],
    }


def _base_patches(mock_sheets: MagicMock) -> list:
    """Return the standard set of patches needed for every push route test."""
    return [
        patch("src.qbo.client.fetch_secret"),
        patch("src.qbo.client.write_secret_cas"),
        patch("intuitlib.client.AuthClient"),
        patch("quickbooks.QuickBooks"),
        patch("src.sheets.client.SheetsClient.from_credentials", return_value=mock_sheets),
        patch("src.sheets.writers.append_log"),
        patch("src.sheets.writers.write_row_status"),
        patch("src.sheets.readers.read_invoices",        return_value=[]),
        patch("src.sheets.readers.read_expenses",        return_value=[]),
        patch("src.sheets.readers.read_sales_receipts",  return_value=[]),
        patch("src.sheets.readers.read_deposits",        return_value=[]),
        patch("src.sheets.readers.read_journal_entries", return_value=[]),
    ]


def _apply_patches(stack: ExitStack, patches: list) -> None:
    for p in patches:
        stack.enter_context(p)


@pytest.fixture
def client() -> FlaskClient:
    app = create_app(_cfg())
    app.config["TESTING"] = True
    return app.test_client()


def _post_push(client, body=None):
    if body is None:
        return client.post("/push")
    return client.post("/push", data=json.dumps(body), content_type="application/json")


# ---------------------------------------------------------------------------
# Backward compatibility: no body / empty body → push all eligible rows
# ---------------------------------------------------------------------------

class TestPushNoSelection:
    def test_no_body_pushes_all_eligible_rows(self, client):
        mock_sheets = _mock_sheets()
        saved = MagicMock()
        saved.Id = "BILL-1"
        mock_pusher = MagicMock(return_value=saved)

        with ExitStack() as stack:
            _apply_patches(stack, _base_patches(mock_sheets))
            stack.enter_context(patch("src.sheets.readers.read_bills",
                                      return_value=[_bill_row(2), _bill_row(3)]))
            stack.enter_context(patch("src.qbo.push.bills.push_bill", mock_pusher))
            resp = _post_push(client)

        assert resp.status_code == 200
        assert resp.get_json()["posted"] == 2
        assert mock_pusher.call_count == 2

    def test_empty_json_object_pushes_all_eligible_rows(self, client):
        mock_sheets = _mock_sheets()
        saved = MagicMock()
        saved.Id = "BILL-1"
        mock_pusher = MagicMock(return_value=saved)

        with ExitStack() as stack:
            _apply_patches(stack, _base_patches(mock_sheets))
            stack.enter_context(patch("src.sheets.readers.read_bills",
                                      return_value=[_bill_row(2)]))
            stack.enter_context(patch("src.qbo.push.bills.push_bill", mock_pusher))
            resp = _post_push(client, {})

        assert resp.status_code == 200
        assert resp.get_json()["posted"] == 1


# ---------------------------------------------------------------------------
# Selection body → only the specified rows are pushed
# ---------------------------------------------------------------------------

class TestPushWithSelection:
    def test_single_row_selected(self, client):
        mock_sheets = _mock_sheets()
        saved = MagicMock()
        saved.Id = "BILL-3"
        mock_pusher = MagicMock(return_value=saved)

        with ExitStack() as stack:
            _apply_patches(stack, _base_patches(mock_sheets))
            stack.enter_context(patch("src.sheets.readers.read_bills",
                                      return_value=[_bill_row(2), _bill_row(3), _bill_row(4)]))
            stack.enter_context(patch("src.qbo.push.bills.push_bill", mock_pusher))
            resp = _post_push(client, {"selection": [{"tab": "Bills", "rows": [3]}]})

        assert resp.status_code == 200
        result = resp.get_json()
        assert result["posted"] == 1
        assert mock_pusher.call_count == 1
        assert mock_pusher.call_args[0][0]["_sheet_row"] == 3

    def test_multiple_rows_selected(self, client):
        mock_sheets = _mock_sheets()
        saved = MagicMock()
        saved.Id = "BILL-X"
        mock_pusher = MagicMock(return_value=saved)

        with ExitStack() as stack:
            _apply_patches(stack, _base_patches(mock_sheets))
            stack.enter_context(patch("src.sheets.readers.read_bills",
                                      return_value=[_bill_row(2), _bill_row(3),
                                                    _bill_row(4), _bill_row(5)]))
            stack.enter_context(patch("src.qbo.push.bills.push_bill", mock_pusher))
            resp = _post_push(client, {"selection": [{"tab": "Bills", "rows": [2, 4]}]})

        assert resp.status_code == 200
        assert resp.get_json()["posted"] == 2
        assert mock_pusher.call_count == 2

    def test_selection_for_different_tab_skips_bills(self, client):
        mock_sheets = _mock_sheets()
        mock_pusher = MagicMock()

        with ExitStack() as stack:
            _apply_patches(stack, _base_patches(mock_sheets))
            stack.enter_context(patch("src.sheets.readers.read_bills",
                                      return_value=[_bill_row(2), _bill_row(3)]))
            stack.enter_context(patch("src.qbo.push.bills.push_bill", mock_pusher))
            resp = _post_push(client, {"selection": [{"tab": "Invoices", "rows": [2, 3]}]})

        assert resp.status_code == 200
        assert resp.get_json()["posted"] == 0
        mock_pusher.assert_not_called()

    def test_empty_rows_list_pushes_nothing(self, client):
        mock_sheets = _mock_sheets()
        mock_pusher = MagicMock()

        with ExitStack() as stack:
            _apply_patches(stack, _base_patches(mock_sheets))
            stack.enter_context(patch("src.sheets.readers.read_bills",
                                      return_value=[_bill_row(2), _bill_row(3)]))
            stack.enter_context(patch("src.qbo.push.bills.push_bill", mock_pusher))
            resp = _post_push(client, {"selection": [{"tab": "Bills", "rows": []}]})

        assert resp.status_code == 200
        assert resp.get_json()["posted"] == 0
        mock_pusher.assert_not_called()

    def test_unknown_tab_in_selection_is_ignored(self, client):
        mock_sheets = _mock_sheets()
        mock_pusher = MagicMock()

        with ExitStack() as stack:
            _apply_patches(stack, _base_patches(mock_sheets))
            stack.enter_context(patch("src.sheets.readers.read_bills",
                                      return_value=[_bill_row(2)]))
            stack.enter_context(patch("src.qbo.push.bills.push_bill", mock_pusher))
            resp = _post_push(client, {"selection": [{"tab": "_Vendors", "rows": [2]}]})

        assert resp.status_code == 200
        assert resp.get_json()["posted"] == 0
        mock_pusher.assert_not_called()


# ---------------------------------------------------------------------------
# Journal Entry selection: include group if ANY row is selected
# ---------------------------------------------------------------------------

class TestPushJournalEntrySelection:
    def _je_base(self, mock_sheets, mock_je_pusher):
        return _base_patches(mock_sheets) + [
            patch("src.sheets.readers.read_bills", return_value=[]),
            patch("src.qbo.push.journal_entries.push_journal_entry", mock_je_pusher),
        ]

    def test_group_included_when_first_row_selected(self, client):
        mock_sheets = _mock_sheets()
        saved = MagicMock()
        saved.Id = "JE-1"
        mock_je_pusher = MagicMock(return_value=saved)

        with ExitStack() as stack:
            _apply_patches(stack, self._je_base(mock_sheets, mock_je_pusher))
            stack.enter_context(patch("src.sheets.readers.read_journal_entries",
                                      return_value=[_je_group([5, 6])]))
            resp = _post_push(client,
                              {"selection": [{"tab": "Journal Entries", "rows": [5]}]})

        assert resp.status_code == 200
        assert resp.get_json()["posted"] == 1
        mock_je_pusher.assert_called_once()

    def test_group_included_when_last_row_selected(self, client):
        mock_sheets = _mock_sheets()
        saved = MagicMock()
        saved.Id = "JE-1"
        mock_je_pusher = MagicMock(return_value=saved)

        with ExitStack() as stack:
            _apply_patches(stack, self._je_base(mock_sheets, mock_je_pusher))
            stack.enter_context(patch("src.sheets.readers.read_journal_entries",
                                      return_value=[_je_group([5, 6])]))
            resp = _post_push(client,
                              {"selection": [{"tab": "Journal Entries", "rows": [6]}]})

        assert resp.status_code == 200
        assert resp.get_json()["posted"] == 1

    def test_group_excluded_when_no_row_selected(self, client):
        mock_sheets = _mock_sheets()
        mock_je_pusher = MagicMock()

        with ExitStack() as stack:
            _apply_patches(stack, self._je_base(mock_sheets, mock_je_pusher))
            stack.enter_context(patch("src.sheets.readers.read_journal_entries",
                                      return_value=[_je_group([5, 6])]))
            resp = _post_push(client,
                              {"selection": [{"tab": "Journal Entries", "rows": [7, 8]}]})

        assert resp.status_code == 200
        assert resp.get_json()["posted"] == 0
        mock_je_pusher.assert_not_called()

    def test_no_selection_pushes_all_je_groups(self, client):
        mock_sheets = _mock_sheets()
        saved = MagicMock()
        saved.Id = "JE-X"
        mock_je_pusher = MagicMock(return_value=saved)

        with ExitStack() as stack:
            _apply_patches(stack, self._je_base(mock_sheets, mock_je_pusher))
            stack.enter_context(patch("src.sheets.readers.read_journal_entries",
                                      return_value=[_je_group([2, 3]), _je_group([4, 5])]))
            resp = _post_push(client)

        assert resp.status_code == 200
        assert resp.get_json()["posted"] == 2
        assert mock_je_pusher.call_count == 2


# ---------------------------------------------------------------------------
# Input validation: malformed selection body returns 400
# ---------------------------------------------------------------------------

class TestPushSelectionValidation:
    def test_selection_not_a_list_returns_400(self, client):
        resp = _post_push(client, {"selection": {"tab": "Bills", "rows": [2]}})
        assert resp.status_code == 400

    def test_selection_entry_not_object_returns_400(self, client):
        resp = _post_push(client, {"selection": ["Bills"]})
        assert resp.status_code == 400

    def test_selection_entry_missing_tab_returns_400(self, client):
        resp = _post_push(client, {"selection": [{"rows": [2]}]})
        assert resp.status_code == 400

    def test_selection_entry_missing_rows_returns_400(self, client):
        resp = _post_push(client, {"selection": [{"tab": "Bills"}]})
        assert resp.status_code == 400

    def test_rows_containing_non_integer_returns_400(self, client):
        resp = _post_push(client, {"selection": [{"tab": "Bills", "rows": ["two"]}]})
        assert resp.status_code == 400
