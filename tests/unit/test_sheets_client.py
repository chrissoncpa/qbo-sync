"""Unit tests for src.sheets.client."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from src.sheets.client import SheetsClient


def _mock_service() -> MagicMock:
    svc = MagicMock()
    # Make chained calls return a mock with an execute() method
    svc.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [["Id", "Name"], ["1", "Checking"]]
    }
    svc.spreadsheets.return_value.values.return_value.update.return_value.execute.return_value = {}
    svc.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
    return svc


class TestReadTab:
    def test_returns_rows(self) -> None:
        svc = _mock_service()
        client = SheetsClient(svc)
        rows = client.read_tab("WB123", "_Accounts")
        assert rows == [["Id", "Name"], ["1", "Checking"]]

    def test_returns_empty_list_when_no_data(self) -> None:
        svc = _mock_service()
        svc.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {}
        client = SheetsClient(svc)
        assert client.read_tab("WB123", "_Accounts") == []


class TestWriteReferenceTab:
    def test_prepends_header_row(self) -> None:
        svc = _mock_service()
        client = SheetsClient(svc)
        client.write_reference_tab("WB123", "_Accounts", ["Id", "Name"], [["1", "Checking"]])

        update_call = svc.spreadsheets.return_value.values.return_value.update
        _, kwargs = update_call.call_args
        assert kwargs["body"]["values"][0] == ["Id", "Name"]
        assert kwargs["body"]["values"][1] == ["1", "Checking"]

    def test_returns_row_count(self) -> None:
        svc = _mock_service()
        client = SheetsClient(svc)
        count = client.write_reference_tab("WB123", "_Accounts", ["Id"], [["1"], ["2"], ["3"]])
        assert count == 3

    def test_uses_raw_value_input(self) -> None:
        svc = _mock_service()
        client = SheetsClient(svc)
        client.write_reference_tab("WB123", "_Accounts", ["Id"], [])

        update_call = svc.spreadsheets.return_value.values.return_value.update
        _, kwargs = update_call.call_args
        assert kwargs["valueInputOption"] == "RAW"


class TestBatchUpdate:
    def test_passes_requests(self) -> None:
        svc = _mock_service()
        client = SheetsClient(svc)
        reqs = [{"addSheet": {"properties": {"title": "_Accounts"}}}]
        client.batch_update("WB123", reqs)

        batch_call = svc.spreadsheets.return_value.batchUpdate
        _, kwargs = batch_call.call_args
        assert kwargs["body"]["requests"] == reqs
