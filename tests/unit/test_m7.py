"""Unit tests for M7: read_deposits, read_journal_entries,
push_deposit, push_journal_entry, validate_journal_balance."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.validators.common import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ref_data():
    return {
        "vendors":     [["Id", "DisplayName", "CompanyName", "Active"],
                        ["10", "ACME Corp", "ACME Corp", "True"]],
        "accounts":    [["Id", "Name", "FullyQualifiedName", "AccountType", "AccountSubType", "Active"],
                        ["100", "Checking", "Checking", "Bank", "Checking", "True"],
                        ["200", "Revenue", "Revenue", "Income", "Other", "True"],
                        ["300", "Office Expenses", "Office Expenses", "Expense", "Other", "True"]],
        "classes":     [["Id", "Name", "FullyQualifiedName", "Active"]],
        "departments": [["Id", "Name", "FullyQualifiedName", "Active"]],
        "customers":   [["Id", "DisplayName", "CompanyName", "Active"]],
        "items":       [["Id", "Name", "FullyQualifiedName", "Type", "Active"]],
    }


def _deposits_header():
    return [
        "RefNumber", "TxnDate", "DepositToAccount", "Memo", "Class", "Location", "Attachment",
        "LineNum", "AccountName", "Description", "Amount", "TaxCode",
        "ClassLine", "LocationLine", "AttachmentLine",
        "Status", "QBO ID", "Posted At",
    ]


def _deposit_row(*, status=""):
    row = [""] * 18
    row[0] = "DEP-001"
    row[1] = "2024-03-01"
    row[2] = "Checking"
    row[8] = "Revenue"
    row[10] = "500.00"
    row[15] = status
    return row


def _je_header():
    return [
        "RefNumber", "TxnDate", "Memo",
        "LineNum", "AccountName", "PostingType", "Amount", "Description",
        "ClassLine", "LocationLine", "EntityName", "EntityType",
        "Status", "QBO ID", "Posted At",
    ]


def _je_row(*, ref="JE-001", account="Checking", posting="Debit", amount="100.00", status=""):
    row = [""] * 15
    row[0] = ref
    row[1] = "2024-03-01"
    row[4] = account
    row[5] = posting
    row[6] = amount
    row[12] = status
    return row


# ---------------------------------------------------------------------------
# validate_journal_balance
# ---------------------------------------------------------------------------

class TestValidateJournalBalance:
    def test_balanced_passes(self):
        from src.validators.balance import validate_journal_balance
        lines = [
            {"PostingType": "Debit",  "Amount": "100.00"},
            {"PostingType": "Credit", "Amount": "100.00"},
        ]
        validate_journal_balance(lines)  # no raise

    def test_unbalanced_raises(self):
        from src.validators.balance import validate_journal_balance
        lines = [
            {"PostingType": "Debit",  "Amount": "100.00"},
            {"PostingType": "Credit", "Amount": "90.00"},
        ]
        with pytest.raises(ValidationError, match="balanced"):
            validate_journal_balance(lines)

    def test_invalid_posting_type_raises(self):
        from src.validators.balance import validate_journal_balance
        with pytest.raises(ValidationError, match="PostingType"):
            validate_journal_balance([{"PostingType": "Transfer", "Amount": "50.00"}])

    def test_within_penny_tolerance_passes(self):
        from src.validators.balance import validate_journal_balance
        lines = [
            {"PostingType": "Debit",  "Amount": "100.00"},
            {"PostingType": "Credit", "Amount": "100.009"},
        ]
        validate_journal_balance(lines)  # difference < 0.01


# ---------------------------------------------------------------------------
# read_deposits
# ---------------------------------------------------------------------------

class TestReadDeposits:
    def test_returns_eligible_rows(self):
        from src.sheets.readers import read_deposits
        sheets = MagicMock()
        sheets.read_tab.return_value = [
            _deposits_header(),
            _deposit_row(status=""),
            _deposit_row(status="posted"),
        ]
        assert len(read_deposits(sheets, "WB")) == 1

    def test_row_has_expected_keys(self):
        from src.sheets.readers import read_deposits
        sheets = MagicMock()
        sheets.read_tab.return_value = [_deposits_header(), _deposit_row()]
        row = read_deposits(sheets, "WB")[0]
        assert row["DepositToAccount"] == "Checking"
        assert row["AccountName"] == "Revenue"
        assert row["Amount"] == "500.00"
        assert "_sheet_row" in row

    def test_empty_tab_returns_empty(self):
        from src.sheets.readers import read_deposits
        sheets = MagicMock()
        sheets.read_tab.return_value = []
        assert read_deposits(sheets, "WB") == []


# ---------------------------------------------------------------------------
# read_journal_entries
# ---------------------------------------------------------------------------

class TestReadJournalEntries:
    def test_groups_rows_by_ref_number(self):
        from src.sheets.readers import read_journal_entries
        sheets = MagicMock()
        sheets.read_tab.return_value = [
            _je_header(),
            _je_row(ref="JE-001", account="Checking",        posting="Debit",  amount="100.00"),
            _je_row(ref="JE-001", account="Revenue",         posting="Credit", amount="100.00"),
            _je_row(ref="JE-002", account="Office Expenses", posting="Debit",  amount="50.00"),
            _je_row(ref="JE-002", account="Checking",        posting="Credit", amount="50.00"),
        ]
        groups = read_journal_entries(sheets, "WB")
        assert len(groups) == 2
        assert len(groups[0]["_lines"]) == 2
        assert groups[0]["RefNumber"] == "JE-001"

    def test_skips_posted_rows(self):
        from src.sheets.readers import read_journal_entries
        sheets = MagicMock()
        sheets.read_tab.return_value = [
            _je_header(),
            _je_row(ref="JE-001", status="posted"),
            _je_row(ref="JE-001", status="posted"),
        ]
        assert read_journal_entries(sheets, "WB") == []

    def test_group_has_sheet_rows(self):
        from src.sheets.readers import read_journal_entries
        sheets = MagicMock()
        sheets.read_tab.return_value = [
            _je_header(),
            _je_row(ref="JE-001"),
            _je_row(ref="JE-001"),
        ]
        group = read_journal_entries(sheets, "WB")[0]
        assert group["_sheet_rows"] == [2, 3]

    def test_empty_tab_returns_empty(self):
        from src.sheets.readers import read_journal_entries
        sheets = MagicMock()
        sheets.read_tab.return_value = []
        assert read_journal_entries(sheets, "WB") == []


# ---------------------------------------------------------------------------
# push_deposit
# ---------------------------------------------------------------------------

class TestPushDeposit:
    def _row(self, **kw):
        defaults = {
            "TxnDate": "2024-03-01", "RefNumber": "DEP-001",
            "DepositToAccount": "Checking", "AccountName": "Revenue",
            "Amount": "500.00", "Description": "March deposit",
            "Memo": "", "Class": "", "ClassLine": "", "Location": "", "LocationLine": "",
            "_sheet_row": 2, "_status_col": 15,
        }
        defaults.update(kw)
        return defaults

    def test_saves_deposit_and_returns_it(self):
        from src.qbo.push.deposits import push_deposit
        mock_saved = MagicMock()
        mock_saved.Id = "DEP-9"
        with patch("quickbooks.objects.Deposit") as MockDep:
            instance = MagicMock()
            instance.save.return_value = mock_saved
            MockDep.return_value = instance
            saved = push_deposit(self._row(), _ref_data(), MagicMock())
        assert saved.Id == "DEP-9"

    def test_raises_for_missing_deposit_account(self):
        from src.qbo.push.deposits import push_deposit
        with pytest.raises(ValidationError, match="DepositToAccount"):
            push_deposit(self._row(DepositToAccount=""), _ref_data(), MagicMock())

    def test_raises_for_unknown_account(self):
        from src.qbo.push.deposits import push_deposit
        with pytest.raises(ValidationError, match="NoSuchAccount"):
            push_deposit(self._row(AccountName="NoSuchAccount"), _ref_data(), MagicMock())


# ---------------------------------------------------------------------------
# push_journal_entry
# ---------------------------------------------------------------------------

class TestPushJournalEntry:
    def _group(self, **kw):
        defaults = {
            "RefNumber": "JE-001",
            "TxnDate": "2024-03-01",
            "Memo": "",
            "_sheet_rows": [2, 3],
            "_status_col": 12,
            "_lines": [
                {"AccountName": "Checking",        "PostingType": "Debit",  "Amount": "100.00", "Description": "", "ClassLine": "", "LocationLine": ""},
                {"AccountName": "Revenue",          "PostingType": "Credit", "Amount": "100.00", "Description": "", "ClassLine": "", "LocationLine": ""},
            ],
        }
        defaults.update(kw)
        return defaults

    def test_saves_je_and_returns_it(self):
        from src.qbo.push.journal_entries import push_journal_entry
        mock_saved = MagicMock()
        mock_saved.Id = "JE-77"
        with patch("quickbooks.objects.JournalEntry") as MockJE:
            instance = MagicMock()
            instance.save.return_value = mock_saved
            MockJE.return_value = instance
            saved = push_journal_entry(self._group(), _ref_data(), MagicMock())
        assert saved.Id == "JE-77"

    def test_raises_for_single_line(self):
        from src.qbo.push.journal_entries import push_journal_entry
        group = self._group()
        group["_lines"] = group["_lines"][:1]
        with pytest.raises(ValidationError, match="at least 2"):
            push_journal_entry(group, _ref_data(), MagicMock())

    def test_raises_for_unbalanced_lines(self):
        from src.qbo.push.journal_entries import push_journal_entry
        group = self._group()
        group["_lines"][1]["Amount"] = "90.00"
        with pytest.raises(ValidationError, match="balanced"):
            push_journal_entry(group, _ref_data(), MagicMock())

    def test_raises_for_missing_txn_date(self):
        from src.qbo.push.journal_entries import push_journal_entry
        with pytest.raises(ValidationError, match="TxnDate"):
            push_journal_entry(self._group(TxnDate=""), _ref_data(), MagicMock())

    def test_raises_for_unknown_account(self):
        from src.qbo.push.journal_entries import push_journal_entry
        group = self._group()
        group["_lines"][0]["AccountName"] = "NoSuchAccount"
        with pytest.raises(ValidationError, match="NoSuchAccount"):
            push_journal_entry(group, _ref_data(), MagicMock())
