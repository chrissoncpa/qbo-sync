"""Unit tests for M9: validate_exchange_rate, currency/tax/terms on push functions,
Terms pull spec."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.validators.common import ValidationError


# ---------------------------------------------------------------------------
# validate_exchange_rate
# ---------------------------------------------------------------------------

class TestValidateExchangeRate:
    def test_returns_none_for_blank(self):
        from src.validators.common import validate_exchange_rate
        assert validate_exchange_rate("") is None
        assert validate_exchange_rate("   ") is None

    def test_parses_float(self):
        from src.validators.common import validate_exchange_rate
        assert validate_exchange_rate("1.25") == 1.25

    def test_strips_commas(self):
        from src.validators.common import validate_exchange_rate
        assert validate_exchange_rate("1,250.00") == 1250.0

    def test_raises_for_non_numeric(self):
        from src.validators.common import validate_exchange_rate
        with pytest.raises(ValidationError, match="number"):
            validate_exchange_rate("abc")

    def test_raises_for_zero(self):
        from src.validators.common import validate_exchange_rate
        with pytest.raises(ValidationError, match="positive"):
            validate_exchange_rate("0")

    def test_raises_for_negative(self):
        from src.validators.common import validate_exchange_rate
        with pytest.raises(ValidationError, match="positive"):
            validate_exchange_rate("-1.5")


# ---------------------------------------------------------------------------
# Terms pull spec
# ---------------------------------------------------------------------------

class TestTermsPullSpec:
    def test_terms_in_pull_specs(self):
        from src.qbo.pull import _PULL_SPECS
        assert "_Terms" in [s.tab_name for s in _PULL_SPECS]

    def test_term_row_extractor(self):
        from src.qbo.pull import _term_row
        term = MagicMock()
        term.Id = "5"
        term.Name = "Net 30"
        term.Active = True
        assert _term_row(term) == ["5", "Net 30", True]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ref_data():
    return {
        "vendors":     [["Id", "DisplayName", "CompanyName", "Active"],
                        ["10", "ACME Corp", "ACME Corp", "True"]],
        "accounts":    [["Id", "Name", "FullyQualifiedName", "AccountType", "AccountSubType", "Active"],
                        ["100", "Checking", "Checking", "Bank", "Checking", "True"],
                        ["200", "Office Expenses", "Office Expenses", "Expense", "Other", "True"],
                        ["201", "Accounts Payable", "Accounts Payable", "AccountsPayable", "AP", "True"],
                        ["202", "Accounts Receivable", "Accounts Receivable", "AccountsReceivable", "AR", "True"]],
        "classes":     [["Id", "Name", "FullyQualifiedName", "Active"]],
        "departments": [["Id", "Name", "FullyQualifiedName", "Active"]],
        "customers":   [["Id", "DisplayName", "CompanyName", "Active"],
                        ["50", "Jane Smith", "Jane Smith", "True"]],
        "items":       [["Id", "Name", "FullyQualifiedName", "Type", "Active"],
                        ["99", "Consulting", "Consulting", "Service", "True"]],
        "terms":       [["Id", "Name", "Active"],
                        ["3", "Net 30", "True"]],
    }


# ---------------------------------------------------------------------------
# push_bill: currency, tax code, AP account, terms
# ---------------------------------------------------------------------------

class TestPushBillM9:
    def _row(self, **kw):
        defaults = {
            "TxnDate": "2024-01-15", "DueDate": "", "RefNumber": "INV-001",
            "VendorName": "ACME Corp", "AccountName": "Office Expenses",
            "Amount": "150.00", "Description": "", "Class": "", "ClassLine": "",
            "Location": "", "LocationLine": "", "Memo": "", "LineType": "",
            "Currency": "", "ExchangeRate": "", "APAccount": "", "TermName": "",
            "TaxCode": "", "_sheet_row": 2, "_status_col": 26,
        }
        defaults.update(kw)
        return defaults

    def _push(self, row):
        from src.qbo.push.bills import push_bill
        mock_saved = MagicMock()
        mock_saved.Id = "BILL-1"
        with patch("quickbooks.objects.Bill") as MockBill:
            instance = MagicMock()
            instance.save.return_value = mock_saved
            MockBill.return_value = instance
            push_bill(row, _ref_data(), MagicMock())
            return instance

    def test_sets_currency_ref(self):
        instance = self._push(self._row(Currency="CAD", ExchangeRate="1.35"))
        assert instance.CurrencyRef.value == "CAD"
        assert instance.ExchangeRate == 1.35

    def test_currency_ref_set_only_when_provided(self):
        from src.qbo.push.bills import push_bill
        mock_saved = MagicMock()
        mock_saved.Id = "BILL-1"
        with patch("quickbooks.objects.Bill") as MockBill:
            instance = MagicMock()
            instance.save.return_value = mock_saved
            MockBill.return_value = instance
            push_bill(self._row(Currency="CAD", ExchangeRate="1.3"), _ref_data(), MagicMock())
        # CurrencyRef must be set when currency is provided
        assert instance.CurrencyRef.value == "CAD"
        assert instance.ExchangeRate == 1.3

    def test_raises_for_bad_exchange_rate(self):
        from src.qbo.push.bills import push_bill
        with pytest.raises(ValidationError, match="ExchangeRate"):
            push_bill(self._row(Currency="CAD", ExchangeRate="bad"), _ref_data(), MagicMock())

    def test_sets_ap_account(self):
        instance = self._push(self._row(APAccount="Accounts Payable"))
        assert instance.APAccountRef.value == "201"

    def test_sets_term(self):
        instance = self._push(self._row(TermName="Net 30"))
        assert instance.SalesTermRef.value == "3"

    def test_raises_for_unknown_term(self):
        from src.qbo.push.bills import push_bill
        with pytest.raises(ValidationError, match="Unknown Term"):
            push_bill(self._row(TermName="Unknown Term"), _ref_data(), MagicMock())


# ---------------------------------------------------------------------------
# push_invoice: currency, tax code, AR account, terms
# ---------------------------------------------------------------------------

class TestPushInvoiceM9:
    def _row(self, **kw):
        defaults = {
            "TxnDate": "2024-01-15", "DueDate": "", "RefNumber": "",
            "CustomerName": "Jane Smith", "ItemName": "Consulting",
            "AccountName": "", "Amount": "500.00", "Description": "",
            "Quantity": "", "UnitPrice": "", "Class": "", "ClassLine": "",
            "Location": "", "LocationLine": "", "Memo": "", "LineType": "",
            "Currency": "", "ExchangeRate": "", "ARAccount": "", "TermName": "",
            "TaxCode": "", "_sheet_row": 2, "_status_col": 24,
        }
        defaults.update(kw)
        return defaults

    def _push(self, row):
        from src.qbo.push.invoices import push_invoice
        mock_saved = MagicMock()
        mock_saved.Id = "INV-1"
        with patch("quickbooks.objects.Invoice") as MockInv:
            instance = MagicMock()
            instance.save.return_value = mock_saved
            MockInv.return_value = instance
            push_invoice(row, _ref_data(), MagicMock())
            return instance

    def test_sets_currency_and_exchange_rate(self):
        instance = self._push(self._row(Currency="EUR", ExchangeRate="0.92"))
        assert instance.CurrencyRef.value == "EUR"
        assert instance.ExchangeRate == 0.92

    def test_sets_ar_account(self):
        instance = self._push(self._row(ARAccount="Accounts Receivable"))
        assert instance.ARAccountRef.value == "202"

    def test_sets_term(self):
        instance = self._push(self._row(TermName="Net 30"))
        assert instance.SalesTermRef.value == "3"


# ---------------------------------------------------------------------------
# push_expense: currency
# ---------------------------------------------------------------------------

class TestPushExpenseM9:
    def _row(self, **kw):
        defaults = {
            "TxnDate": "2024-01-15", "RefNumber": "",
            "PaymentType": "Cash", "PaymentAccount": "Checking",
            "VendorName": "", "AccountName": "Office Expenses",
            "Amount": "75.00", "Description": "", "Class": "", "ClassLine": "",
            "Location": "", "LocationLine": "", "Memo": "", "CustomerName": "",
            "Currency": "", "ExchangeRate": "", "TaxCode": "",
            "_sheet_row": 2, "_status_col": 25,
        }
        defaults.update(kw)
        return defaults

    def test_sets_currency(self):
        from src.qbo.push.expenses import push_expense
        mock_saved = MagicMock()
        mock_saved.Id = "EXP-1"
        with patch("quickbooks.objects.Purchase") as MockP:
            instance = MagicMock()
            instance.save.return_value = mock_saved
            MockP.return_value = instance
            push_expense(self._row(Currency="GBP", ExchangeRate="0.80"), _ref_data(), MagicMock())
        assert instance.CurrencyRef.value == "GBP"
        assert instance.ExchangeRate == 0.80
