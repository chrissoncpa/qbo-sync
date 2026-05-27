"""Unit tests for M6: read_invoices, read_expenses, read_sales_receipts,
push_invoice, push_expense, push_sales_receipt, and pull _Items."""

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
                        ["200", "Checking", "Checking", "Bank", "Checking", "True"],
                        ["201", "Office Expenses", "Office Expenses", "Expense", "Other", "True"]],
        "classes":     [["Id", "Name", "FullyQualifiedName", "Active"]],
        "departments": [["Id", "Name", "FullyQualifiedName", "Active"]],
        "customers":   [["Id", "DisplayName", "CompanyName", "Active"],
                        ["50", "Jane Smith", "Jane Smith", "True"]],
        "items":       [["Id", "Name", "FullyQualifiedName", "Type", "Active"],
                        ["99", "Consulting", "Consulting", "Service", "True"]],
    }


def _invoices_header():
    return [
        "RefNumber", "TxnDate", "DueDate", "CustomerName", "Currency", "ExchangeRate",
        "ARAccount", "Class", "Location", "TermName", "Memo", "Attachment",
        "LineNum", "LineType", "ItemName", "AccountName", "Description",
        "Quantity", "UnitPrice", "Amount", "TaxCode",
        "ClassLine", "LocationLine", "AttachmentLine",
        "Status", "QBO ID", "Posted At",
    ]


def _expenses_header():
    return [
        "RefNumber", "TxnDate", "PaymentType", "PaymentAccount", "VendorName",
        "Currency", "ExchangeRate", "Class", "Location", "Memo", "Attachment",
        "LineNum", "LineType", "AccountName", "ItemName", "Description",
        "Quantity", "UnitPrice", "Amount", "TaxCode",
        "ClassLine", "LocationLine", "CustomerName", "Billable", "AttachmentLine",
        "Status", "QBO ID", "Posted At",
    ]


def _sales_receipts_header():
    return [
        "RefNumber", "TxnDate", "CustomerName", "Currency", "ExchangeRate",
        "DepositToAccount", "Class", "Location", "Memo", "Attachment",
        "LineNum", "LineType", "ItemName", "AccountName", "Description",
        "Quantity", "UnitPrice", "Amount", "TaxCode",
        "ClassLine", "LocationLine", "AttachmentLine",
        "Status", "QBO ID", "Posted At",
    ]


def _invoice_row(*, status=""):
    row = [""] * 27
    row[0] = "INV-001"
    row[1] = "2024-02-01"
    row[3] = "Jane Smith"
    row[14] = "Consulting"
    row[19] = "500.00"
    row[24] = status
    return row


def _expense_row(*, status=""):
    row = [""] * 28
    row[0] = "EXP-001"
    row[1] = "2024-02-01"
    row[2] = "Cash"
    row[3] = "Checking"
    row[13] = "Office Expenses"
    row[18] = "75.00"
    row[25] = status
    return row


def _sales_receipt_row(*, status=""):
    row = [""] * 25
    row[0] = "SR-001"
    row[1] = "2024-02-01"
    row[2] = "Jane Smith"
    row[12] = "Consulting"
    row[17] = "250.00"
    row[22] = status
    return row


# ---------------------------------------------------------------------------
# read_invoices
# ---------------------------------------------------------------------------

class TestReadInvoices:
    def test_returns_eligible_rows(self):
        from src.sheets.readers import read_invoices
        sheets = MagicMock()
        sheets.read_tab.return_value = [
            _invoices_header(),
            _invoice_row(status=""),
            _invoice_row(status="posted"),
        ]
        assert len(read_invoices(sheets, "WB")) == 1

    def test_row_has_expected_keys(self):
        from src.sheets.readers import read_invoices
        sheets = MagicMock()
        sheets.read_tab.return_value = [_invoices_header(), _invoice_row()]
        row = read_invoices(sheets, "WB")[0]
        assert row["CustomerName"] == "Jane Smith"
        assert row["ItemName"] == "Consulting"
        assert row["Amount"] == "500.00"
        assert "_sheet_row" in row
        assert "_status_col" in row

    def test_empty_tab_returns_empty(self):
        from src.sheets.readers import read_invoices
        sheets = MagicMock()
        sheets.read_tab.return_value = []
        assert read_invoices(sheets, "WB") == []


# ---------------------------------------------------------------------------
# read_expenses
# ---------------------------------------------------------------------------

class TestReadExpenses:
    def test_returns_eligible_rows(self):
        from src.sheets.readers import read_expenses
        sheets = MagicMock()
        sheets.read_tab.return_value = [
            _expenses_header(),
            _expense_row(status=""),
            _expense_row(status="error: x"),
        ]
        assert len(read_expenses(sheets, "WB")) == 1

    def test_row_has_expected_keys(self):
        from src.sheets.readers import read_expenses
        sheets = MagicMock()
        sheets.read_tab.return_value = [_expenses_header(), _expense_row()]
        row = read_expenses(sheets, "WB")[0]
        assert row["PaymentType"] == "Cash"
        assert row["PaymentAccount"] == "Checking"
        assert row["AccountName"] == "Office Expenses"
        assert row["Amount"] == "75.00"


# ---------------------------------------------------------------------------
# read_sales_receipts
# ---------------------------------------------------------------------------

class TestReadSalesReceipts:
    def test_returns_eligible_rows(self):
        from src.sheets.readers import read_sales_receipts
        sheets = MagicMock()
        sheets.read_tab.return_value = [
            _sales_receipts_header(),
            _sales_receipt_row(status=""),
            _sales_receipt_row(status="posted"),
        ]
        assert len(read_sales_receipts(sheets, "WB")) == 1

    def test_row_has_expected_keys(self):
        from src.sheets.readers import read_sales_receipts
        sheets = MagicMock()
        sheets.read_tab.return_value = [_sales_receipts_header(), _sales_receipt_row()]
        row = read_sales_receipts(sheets, "WB")[0]
        assert row["CustomerName"] == "Jane Smith"
        assert row["ItemName"] == "Consulting"
        assert row["Amount"] == "250.00"


# ---------------------------------------------------------------------------
# push_invoice
# ---------------------------------------------------------------------------

class TestPushInvoice:
    def _row(self, **kw):
        defaults = {
            "TxnDate": "2024-02-01", "DueDate": "", "RefNumber": "INV-001",
            "CustomerName": "Jane Smith", "ItemName": "Consulting",
            "AccountName": "", "Amount": "500.00", "Description": "Advisory",
            "Quantity": "5", "UnitPrice": "100.00",
            "Class": "", "ClassLine": "", "Location": "", "LocationLine": "",
            "Memo": "", "_sheet_row": 2, "_status_col": 24,
        }
        defaults.update(kw)
        return defaults

    def test_saves_invoice_and_returns_it(self):
        from src.qbo.push.invoices import push_invoice
        mock_saved = MagicMock()
        mock_saved.Id = "INV-42"
        with patch("quickbooks.objects.Invoice") as MockInv:
            instance = MagicMock()
            instance.save.return_value = mock_saved
            MockInv.return_value = instance
            saved = push_invoice(self._row(), _ref_data(), MagicMock())
        assert saved.Id == "INV-42"

    def test_raises_for_missing_customer(self):
        from src.qbo.push.invoices import push_invoice
        with pytest.raises(ValidationError, match="CustomerName"):
            push_invoice(self._row(CustomerName=""), _ref_data(), MagicMock())

    def test_raises_for_unknown_customer(self):
        from src.qbo.push.invoices import push_invoice
        with pytest.raises(ValidationError, match="Unknown"):
            push_invoice(self._row(CustomerName="Unknown"), _ref_data(), MagicMock())

    def test_raises_for_unknown_item(self):
        from src.qbo.push.invoices import push_invoice
        with pytest.raises(ValidationError, match="NoSuchItem"):
            push_invoice(self._row(ItemName="NoSuchItem"), _ref_data(), MagicMock())


# ---------------------------------------------------------------------------
# push_expense
# ---------------------------------------------------------------------------

class TestPushExpense:
    def _row(self, **kw):
        defaults = {
            "TxnDate": "2024-02-01", "RefNumber": "EXP-001",
            "PaymentType": "Cash", "PaymentAccount": "Checking",
            "VendorName": "", "AccountName": "Office Expenses",
            "Amount": "75.00", "Description": "Supplies",
            "Class": "", "ClassLine": "", "Location": "", "LocationLine": "",
            "Memo": "", "CustomerName": "", "_sheet_row": 2, "_status_col": 25,
        }
        defaults.update(kw)
        return defaults

    def test_saves_expense_and_returns_it(self):
        from src.qbo.push.expenses import push_expense
        mock_saved = MagicMock()
        mock_saved.Id = "EXP-7"
        with patch("quickbooks.objects.Purchase") as MockPurchase:
            instance = MagicMock()
            instance.save.return_value = mock_saved
            MockPurchase.return_value = instance
            saved = push_expense(self._row(), _ref_data(), MagicMock())
        assert saved.Id == "EXP-7"

    def test_raises_for_invalid_payment_type(self):
        from src.qbo.push.expenses import push_expense
        with pytest.raises(ValidationError, match="PaymentType"):
            push_expense(self._row(PaymentType="Wire"), _ref_data(), MagicMock())

    def test_raises_for_missing_payment_account(self):
        from src.qbo.push.expenses import push_expense
        with pytest.raises(ValidationError, match="PaymentAccount"):
            push_expense(self._row(PaymentAccount=""), _ref_data(), MagicMock())

    def test_raises_for_unknown_account(self):
        from src.qbo.push.expenses import push_expense
        with pytest.raises(ValidationError, match="NoSuchAccount"):
            push_expense(self._row(AccountName="NoSuchAccount"), _ref_data(), MagicMock())


# ---------------------------------------------------------------------------
# push_sales_receipt
# ---------------------------------------------------------------------------

class TestPushSalesReceipt:
    def _row(self, **kw):
        defaults = {
            "TxnDate": "2024-02-01", "RefNumber": "SR-001",
            "CustomerName": "Jane Smith", "ItemName": "Consulting",
            "Amount": "250.00", "Description": "Session",
            "Quantity": "", "UnitPrice": "",
            "DepositToAccount": "", "Class": "", "ClassLine": "",
            "Location": "", "LocationLine": "", "Memo": "",
            "_sheet_row": 2, "_status_col": 22,
        }
        defaults.update(kw)
        return defaults

    def test_saves_receipt_and_returns_it(self):
        from src.qbo.push.sales_receipts import push_sales_receipt
        mock_saved = MagicMock()
        mock_saved.Id = "SR-5"
        with patch("quickbooks.objects.SalesReceipt") as MockSR:
            instance = MagicMock()
            instance.save.return_value = mock_saved
            MockSR.return_value = instance
            saved = push_sales_receipt(self._row(), _ref_data(), MagicMock())
        assert saved.Id == "SR-5"

    def test_raises_for_missing_customer(self):
        from src.qbo.push.sales_receipts import push_sales_receipt
        with pytest.raises(ValidationError, match="CustomerName"):
            push_sales_receipt(self._row(CustomerName=""), _ref_data(), MagicMock())

    def test_raises_for_unknown_item(self):
        from src.qbo.push.sales_receipts import push_sales_receipt
        with pytest.raises(ValidationError, match="NoSuchItem"):
            push_sales_receipt(self._row(ItemName="NoSuchItem"), _ref_data(), MagicMock())


# ---------------------------------------------------------------------------
# pull _Items
# ---------------------------------------------------------------------------

class TestPullItems:
    def test_items_tab_in_pull_specs(self):
        from src.qbo.pull import _PULL_SPECS
        tab_names = [s.tab_name for s in _PULL_SPECS]
        assert "_Items" in tab_names

    def test_item_row_extractor(self):
        from src.qbo.pull import _item_row
        item = MagicMock()
        item.Id = "99"
        item.Name = "Consulting"
        item.FullyQualifiedName = "Consulting"
        item.Type = "Service"
        item.Active = True
        assert _item_row(item) == ["99", "Consulting", "Consulting", "Service", True]
