"""Unit tests for M5: idempotency, readers, validators, push/bills, writers, /push route."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from flask.testing import FlaskClient

from src.app import create_app
from src.config import Config
from src.utils.idempotency import is_eligible_for_push
from src.validators.common import ValidationError, resolve_entity, validate_currency, validate_required


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(**kw) -> Config:
    defaults = dict(
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
    defaults.update(kw)
    return Config(**defaults)


def _bills_header():
    return [
        "RefNumber", "TxnDate", "DueDate", "VendorName", "Currency", "ExchangeRate",
        "APAccount", "Class", "Location", "TermName", "Memo", "Attachment",
        "LineNum", "LineType", "AccountName", "ItemName", "Description",
        "Quantity", "UnitPrice", "Amount", "TaxCode",
        "ClassLine", "LocationLine", "CustomerName", "Billable", "AttachmentLine",
        "Status", "QBO ID", "Posted At",
    ]


def _bill_data_row(
    *,
    ref_number="INV-001",
    txn_date="2024-01-15",
    vendor_name="ACME Corp",
    account_name="Office Expenses",
    amount="150.00",
    status="",
):
    row = [""] * 29
    row[0] = ref_number
    row[1] = txn_date
    row[3] = vendor_name
    row[14] = account_name
    row[19] = amount
    row[26] = status
    return row


def _ref_data():
    return {
        "vendors":     [["Id", "DisplayName", "CompanyName", "Active"],
                        ["10", "ACME Corp", "ACME Corp", "True"]],
        "accounts":    [["Id", "Name", "FullyQualifiedName", "AccountType", "AccountSubType", "Active"],
                        ["200", "Office Expenses", "Office Expenses", "Expense", "Other", "True"]],
        "classes":     [["Id", "Name", "FullyQualifiedName", "Active"]],
        "departments": [["Id", "Name", "FullyQualifiedName", "Active"]],
    }


# ---------------------------------------------------------------------------
# is_eligible_for_push
# ---------------------------------------------------------------------------

class TestIsEligibleForPush:
    def test_empty_string_is_eligible(self):
        assert is_eligible_for_push("") is True

    def test_none_is_eligible(self):
        assert is_eligible_for_push(None) is True

    def test_whitespace_is_eligible(self):
        assert is_eligible_for_push("   ") is True

    def test_posted_is_not_eligible(self):
        assert is_eligible_for_push("posted") is False

    def test_error_is_not_eligible(self):
        assert is_eligible_for_push("error: missing vendor") is False


# ---------------------------------------------------------------------------
# validate_required
# ---------------------------------------------------------------------------

class TestValidateRequired:
    def test_passes_when_all_present(self):
        validate_required({"a": "1", "b": "2"}, ["a", "b"])  # no raise

    def test_raises_for_missing_field(self):
        with pytest.raises(ValidationError, match="TxnDate"):
            validate_required({"VendorName": "X"}, ["TxnDate", "VendorName"])

    def test_raises_for_blank_field(self):
        with pytest.raises(ValidationError, match="Amount"):
            validate_required({"Amount": "  "}, ["Amount"])


# ---------------------------------------------------------------------------
# resolve_entity
# ---------------------------------------------------------------------------

class TestResolveEntity:
    def _rows(self):
        return [["10", "ACME Corp", "ACME Corp", "True"],
                ["11", "Beta LLC",  "Beta LLC",  "True"]]

    def test_finds_by_name(self):
        assert resolve_entity("ACME Corp", self._rows(), name_col_idx=1) == "10"

    def test_raises_when_not_found(self):
        with pytest.raises(ValidationError, match="Nonexistent"):
            resolve_entity("Nonexistent", self._rows(), name_col_idx=1)

    def test_raises_for_blank_name(self):
        with pytest.raises(ValidationError, match="blank"):
            resolve_entity("", self._rows(), name_col_idx=1)

    def test_case_sensitive(self):
        with pytest.raises(ValidationError):
            resolve_entity("acme corp", self._rows(), name_col_idx=1)


# ---------------------------------------------------------------------------
# validate_currency
# ---------------------------------------------------------------------------

class TestValidateCurrency:
    def test_parses_float(self):
        assert validate_currency("150.00") == 150.0

    def test_strips_commas(self):
        assert validate_currency("1,500.00") == 1500.0

    def test_raises_for_non_numeric(self):
        with pytest.raises(ValidationError):
            validate_currency("abc")

    def test_raises_for_negative(self):
        with pytest.raises(ValidationError):
            validate_currency("-10.00")


# ---------------------------------------------------------------------------
# read_bills
# ---------------------------------------------------------------------------

class TestReadBills:
    def test_returns_eligible_rows(self):
        from src.sheets.readers import read_bills

        sheets = MagicMock()
        sheets.read_tab.return_value = [
            _bills_header(),
            _bill_data_row(status=""),          # eligible
            _bill_data_row(status="posted"),     # skip
            _bill_data_row(status="error: x"),   # skip
        ]
        rows = read_bills(sheets, "WB123")
        assert len(rows) == 1

    def test_row_dict_has_expected_keys(self):
        from src.sheets.readers import read_bills

        sheets = MagicMock()
        sheets.read_tab.return_value = [_bills_header(), _bill_data_row()]
        row = read_bills(sheets, "WB123")[0]
        assert row["VendorName"] == "ACME Corp"
        assert row["TxnDate"] == "2024-01-15"
        assert row["Amount"] == "150.00"
        assert "_sheet_row" in row
        assert "_status_col" in row

    def test_sheet_row_starts_at_2(self):
        from src.sheets.readers import read_bills

        sheets = MagicMock()
        sheets.read_tab.return_value = [_bills_header(), _bill_data_row()]
        row = read_bills(sheets, "WB123")[0]
        assert row["_sheet_row"] == 2

    def test_empty_tab_returns_empty_list(self):
        from src.sheets.readers import read_bills

        sheets = MagicMock()
        sheets.read_tab.return_value = []
        assert read_bills(sheets, "WB123") == []


# ---------------------------------------------------------------------------
# push_bill
# ---------------------------------------------------------------------------

class TestPushBill:
    def _row(self, **kw):
        defaults = {
            "TxnDate": "2024-01-15", "DueDate": "", "RefNumber": "INV-001",
            "VendorName": "ACME Corp", "AccountName": "Office Expenses",
            "Amount": "150.00", "Description": "Office supplies",
            "Class": "", "ClassLine": "", "Location": "", "LocationLine": "",
            "Memo": "", "LineType": "", "_sheet_row": 2, "_status_col": 26,
        }
        defaults.update(kw)
        return defaults

    def test_saves_bill_and_returns_it(self):
        from src.qbo.push.bills import push_bill

        mock_bill = MagicMock()
        mock_bill.Id = "BILL-42"

        with patch("quickbooks.objects.Bill") as MockBill:
            instance = MagicMock()
            instance.save.return_value = mock_bill
            MockBill.return_value = instance

            saved = push_bill(self._row(), _ref_data(), MagicMock())

        assert saved.Id == "BILL-42"

    def test_raises_for_missing_required_field(self):
        from src.qbo.push.bills import push_bill

        with pytest.raises(ValidationError, match="VendorName"):
            push_bill(self._row(VendorName=""), _ref_data(), MagicMock())

    def test_raises_for_item_line_type(self):
        from src.qbo.push.bills import push_bill

        with pytest.raises(ValidationError, match="Item"):
            push_bill(self._row(LineType="Item"), _ref_data(), MagicMock())

    def test_raises_when_vendor_not_in_ref(self):
        from src.qbo.push.bills import push_bill

        with pytest.raises(ValidationError, match="Unknown Vendor"):
            push_bill(self._row(VendorName="Unknown Vendor"), _ref_data(), MagicMock())


# ---------------------------------------------------------------------------
# write_row_status / append_log
# ---------------------------------------------------------------------------

class TestWriteRowStatus:
    def test_writes_to_correct_range(self):
        from src.sheets.writers import write_row_status

        sheets = MagicMock()
        write_row_status(sheets, "WB123", "Bills", 5, 26, "posted", "BILL-1", "2024-01-15T00:00:00Z")

        sheets.write_range.assert_called_once_with(
            "WB123", "Bills!AA5:AC5", [["posted", "BILL-1", "2024-01-15T00:00:00Z"]]
        )

    def test_col_letter_conversion(self):
        from src.sheets.writers import _col_letter

        assert _col_letter(0) == "A"
        assert _col_letter(25) == "Z"
        assert _col_letter(26) == "AA"
        assert _col_letter(26 + 25) == "AZ"
        assert _col_letter(52) == "BA"


class TestAppendLog:
    def test_calls_sheets_append(self):
        from src.sheets.writers import append_log

        svc = MagicMock()
        sheets = MagicMock()
        sheets._svc = svc
        svc.spreadsheets.return_value.values.return_value.append.return_value.execute.return_value = {}

        append_log(sheets, "WB123", "2024-01-15T00:00:00Z", "push", "Bills", 3, 2, 1, 0)

        svc.spreadsheets.return_value.values.return_value.append.assert_called_once()


# ---------------------------------------------------------------------------
# /push route integration
# ---------------------------------------------------------------------------

class TestPushRoute:
    @pytest.fixture
    def client(self) -> FlaskClient:
        app = create_app(_cfg())
        app.config["TESTING"] = True
        return app.test_client()

    def _mock_push_deps(self, posted=1, errored=0):
        """Context managers that mock out all I/O for the /push route."""
        mock_qb = MagicMock()
        mock_sheets = MagicMock()
        mock_sheets.read_tab.return_value = []
        mock_sheets._svc = MagicMock()
        mock_sheets._svc.spreadsheets.return_value.values.return_value.append.return_value.execute.return_value = {}

        saved_bill = MagicMock()
        saved_bill.Id = "BILL-99"

        return (
            patch("src.qbo.client.fetch_secret"),
            patch("src.qbo.client.write_secret_cas"),
            patch("intuitlib.client.AuthClient"),
            patch("quickbooks.QuickBooks", return_value=mock_qb),
            patch("src.sheets.client.SheetsClient.from_credentials", return_value=mock_sheets),
            patch("src.sheets.readers.read_bills", return_value=[]),
            patch("src.sheets.writers.append_log"),
        )

    def test_returns_200_with_summary(self, client: FlaskClient) -> None:
        with (
            patch("src.qbo.client.fetch_secret"),
            patch("src.qbo.client.write_secret_cas"),
            patch("intuitlib.client.AuthClient"),
            patch("quickbooks.QuickBooks"),
            patch("src.sheets.client.SheetsClient.from_credentials", return_value=MagicMock(
                read_tab=MagicMock(return_value=[]),
                _svc=MagicMock(**{"spreadsheets.return_value.values.return_value.append.return_value.execute.return_value": {}}),
            )),
            patch("src.sheets.readers.read_bills", return_value=[]),
            patch("src.sheets.writers.append_log"),
        ):
            resp = client.post("/push")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert body["posted"] == 0

    def test_returns_500_when_workbook_not_configured(self) -> None:
        app = create_app(_cfg(workbook_id=""))
        resp = app.test_client().post("/push")
        assert resp.status_code == 500

    def test_requires_oidc_when_email_set(self) -> None:
        app = create_app(_cfg(allowed_invoker_email="admin@example.com"))
        resp = app.test_client().post("/push")
        assert resp.status_code == 401

    def test_health_still_passes(self, client: FlaskClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
