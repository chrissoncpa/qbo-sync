"""Unit tests for src.sheets.validation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from src.sheets.validation import _make_validation_request, refresh_validation_rules


def _cfg(workbook_id: str = "WB123"):
    return SimpleNamespace(workbook_id=workbook_id)


def _sheets_with_tabs(*tab_names: str) -> MagicMock:
    """Return a mock SheetsClient whose metadata lists the given tab names."""
    svc = MagicMock()
    sheets = MagicMock()
    sheets._svc = svc

    metadata = {
        "sheets": [
            {"properties": {"title": name, "sheetId": idx}}
            for idx, name in enumerate(tab_names)
        ]
    }
    svc.spreadsheets.return_value.get.return_value.execute.return_value = metadata
    svc.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}

    # Default: return empty header row for all tabs
    sheets.read_tab.return_value = []
    return sheets


class TestRefreshValidationRules:
    def test_returns_zero_when_no_transaction_tabs_exist(self) -> None:
        sheets = _sheets_with_tabs("_Accounts", "_Vendors")  # no transaction tabs
        result = refresh_validation_rules(_cfg(), sheets)
        assert result == 0
        sheets.batch_update.assert_not_called()

    def test_skips_tabs_absent_from_workbook(self) -> None:
        sheets = _sheets_with_tabs("Bills")  # only Bills exists
        sheets.read_tab.return_value = [["Date", "Vendor", "Amount"]]
        result = refresh_validation_rules(_cfg(), sheets)
        # Only Vendor column on Bills tab → 1 rule
        assert result == 1

    def test_applies_rule_for_each_matching_column(self) -> None:
        sheets = _sheets_with_tabs("Bills")
        sheets.read_tab.return_value = [["Date", "Vendor", "Account", "Amount"]]

        result = refresh_validation_rules(_cfg(), sheets)

        assert result == 2  # Vendor + Account

    def test_ignores_unrecognised_column_headers(self) -> None:
        sheets = _sheets_with_tabs("Bills")
        sheets.read_tab.return_value = [["Date", "Memo", "Amount", "Reference"]]

        result = refresh_validation_rules(_cfg(), sheets)
        assert result == 0

    def test_batch_update_called_with_correct_ref_range(self) -> None:
        sheets = _sheets_with_tabs("Invoices")
        sheets.read_tab.return_value = [["Date", "Customer", "Amount"]]

        refresh_validation_rules(_cfg(), sheets)

        _, kwargs = sheets.batch_update.call_args
        requests = kwargs if kwargs else sheets.batch_update.call_args[0][1]
        # Unpack: batch_update(workbook_id, requests)
        call_args = sheets.batch_update.call_args
        workbook_id_arg = call_args[0][0]
        validation_requests = call_args[0][1]

        assert workbook_id_arg == "WB123"
        assert len(validation_requests) == 1
        rule = validation_requests[0]["setDataValidation"]["rule"]
        assert "ONE_OF_RANGE" == rule["condition"]["type"]
        assert "_Customers" in rule["condition"]["values"][0]["userEnteredValue"]

    def test_correct_column_index_used(self) -> None:
        sheets = _sheets_with_tabs("Bills")
        # Vendor is at index 2
        sheets.read_tab.return_value = [["Date", "Amount", "Vendor"]]

        refresh_validation_rules(_cfg(), sheets)

        call_args = sheets.batch_update.call_args[0]
        req = call_args[1][0]["setDataValidation"]["range"]
        assert req["startColumnIndex"] == 2
        assert req["endColumnIndex"] == 3

    def test_all_transaction_tabs_scanned(self) -> None:
        tab_names = ["Bills", "Invoices", "Expenses", "Sales Receipts", "Deposits", "Journal Entries"]
        sheets = _sheets_with_tabs(*tab_names)
        # Each tab has one Account column
        sheets.read_tab.return_value = [["Account"]]

        result = refresh_validation_rules(_cfg(), sheets)

        assert result == len(tab_names)
        assert sheets.read_tab.call_count == len(tab_names)

    def test_no_batch_update_when_no_rules(self) -> None:
        sheets = _sheets_with_tabs("Bills")
        sheets.read_tab.return_value = [["Date", "Amount"]]

        refresh_validation_rules(_cfg(), sheets)

        sheets.batch_update.assert_not_called()


class TestMakeValidationRequest:
    def test_structure(self) -> None:
        req = _make_validation_request(
            sheet_id=42, col_idx=3, ref_tab="_Vendors", ref_col="B"
        )
        r = req["setDataValidation"]
        assert r["range"]["sheetId"] == 42
        assert r["range"]["startColumnIndex"] == 3
        assert r["range"]["endColumnIndex"] == 4
        assert r["range"]["startRowIndex"] == 1
        assert r["rule"]["condition"]["type"] == "ONE_OF_RANGE"
        assert "'_Vendors'!$B$2:$B$1001" in r["rule"]["condition"]["values"][0]["userEnteredValue"]
        assert r["rule"]["showCustomUi"] is True
        assert r["rule"]["strict"] is False


class TestRunPullCallsValidation:
    def test_refresh_validation_called_after_tabs_written(self) -> None:
        from src.config import Config
        from src.qbo.pull import run_pull

        cfg = Config(
            project_id="p",
            environment="sandbox",
            workbook_id="WB",
            drive_inbox_folder_id="",
            drive_archive_root_id="",
            allowed_invoker_email="",
            is_cloud_run=False,
            oauth_redirect_uri="",
            flask_secret_key="t",
        )
        mock_sheets = MagicMock()
        mock_sheets.write_reference_tab.return_value = 0

        with (
            patch("src.qbo.pull.get_qbo_client", return_value=MagicMock()),
            patch("src.qbo.pull.SheetsClient.from_credentials", return_value=mock_sheets),
            patch("quickbooks.objects.Account.all", return_value=[]),
            patch("quickbooks.objects.Vendor.all", return_value=[]),
            patch("quickbooks.objects.Customer.all", return_value=[]),
            patch("quickbooks.objects.Class.all", return_value=[]),
            patch("quickbooks.objects.Department.all", return_value=[]),
            patch("src.qbo.pull.refresh_validation_rules", return_value=4) as mock_val,
        ):
            run_pull(cfg)

        mock_val.assert_called_once_with(cfg, mock_sheets)
