"""Unit tests for src.qbo.pull and the /pull Flask route."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

from src.app import create_app
from src.config import Config
from src.qbo.pull import PullResult, run_pull


def _cfg(**overrides) -> Config:
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
    defaults.update(overrides)
    return Config(**defaults)


def _fake_account(id_: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(
        Id=id_,
        Name=name,
        FullyQualifiedName=name,
        AccountType="Bank",
        AccountSubType="Checking",
        Active=True,
    )


def _fake_vendor(id_: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(Id=id_, DisplayName=name, CompanyName=name, Active=True)


def _fake_customer(id_: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(Id=id_, DisplayName=name, CompanyName=name, Active=True)


def _fake_class(id_: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(Id=id_, Name=name, FullyQualifiedName=name, Active=True)


def _fake_dept(id_: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(Id=id_, Name=name, FullyQualifiedName=name, Active=True)


class TestRunPull:
    def test_writes_all_tabs(self) -> None:
        cfg = _cfg()
        mock_qb = MagicMock()
        mock_sheets = MagicMock()
        mock_sheets.write_reference_tab.return_value = 2

        entity_data = {
            "Account": [_fake_account("1", "Checking"), _fake_account("2", "Savings")],
            "Vendor": [_fake_vendor("10", "ACME")],
            "Customer": [_fake_customer("20", "Bob")],
            "Class": [_fake_class("30", "Operations")],
            "Department": [_fake_dept("40", "HQ")],
        }

        def fake_all(qb, max_results):
            # Called as Entity.all(qb=..., max_results=...)
            return []

        with (
            patch("src.qbo.pull.get_qbo_client", return_value=mock_qb),
            patch("src.qbo.pull.SheetsClient.from_credentials", return_value=mock_sheets),
            patch("quickbooks.objects.Account.all", return_value=entity_data["Account"]),
            patch("quickbooks.objects.Vendor.all", return_value=entity_data["Vendor"]),
            patch("quickbooks.objects.Customer.all", return_value=entity_data["Customer"]),
            patch("quickbooks.objects.Class.all", return_value=entity_data["Class"]),
            patch("quickbooks.objects.Department.all", return_value=entity_data["Department"]),
        ):
            results = run_pull(cfg)

        tab_names = [r.tab for r in results]
        assert "_Accounts" in tab_names
        assert "_Vendors" in tab_names
        assert "_Customers" in tab_names
        assert "_Classes" in tab_names
        assert "_Departments" in tab_names

    def test_returns_pull_results(self) -> None:
        cfg = _cfg()
        mock_qb = MagicMock()
        mock_sheets = MagicMock()
        mock_sheets.write_reference_tab.return_value = 3

        with (
            patch("src.qbo.pull.get_qbo_client", return_value=mock_qb),
            patch("src.qbo.pull.SheetsClient.from_credentials", return_value=mock_sheets),
            patch("quickbooks.objects.Account.all", return_value=[_fake_account("1", "X")] * 3),
            patch("quickbooks.objects.Vendor.all", return_value=[]),
            patch("quickbooks.objects.Customer.all", return_value=[]),
            patch("quickbooks.objects.Class.all", return_value=[]),
            patch("quickbooks.objects.Department.all", return_value=[]),
        ):
            results = run_pull(cfg)

        accounts = next(r for r in results if r.tab == "_Accounts")
        assert accounts.rows_written == 3


class TestPullRoute:
    @pytest.fixture
    def client(self) -> FlaskClient:
        app = create_app(_cfg())
        app.config["TESTING"] = True
        return app.test_client()

    def test_returns_200_with_summary(self, client: FlaskClient) -> None:
        pull_results = [
            PullResult(tab="_Accounts", rows_written=5),
            PullResult(tab="_Vendors", rows_written=3),
        ]
        with patch("src.qbo.pull.run_pull", return_value=pull_results):
            resp = client.post("/pull")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert body["tabs"]["_Accounts"] == 5
        assert body["tabs"]["_Vendors"] == 3

    def test_returns_500_when_workbook_not_configured(self) -> None:
        app = create_app(_cfg(workbook_id=""))
        app.config["TESTING"] = True
        resp = app.test_client().post("/pull")
        assert resp.status_code == 500
        assert "WORKBOOK_ID" in resp.get_json()["error"]

    def test_requires_oidc_when_invoker_email_set(self) -> None:
        app = create_app(_cfg(allowed_invoker_email="admin@example.com"))
        app.config["TESTING"] = True
        resp = app.test_client().post("/pull")  # no Authorization header
        assert resp.status_code == 401

    def test_oidc_passes_with_valid_token(self) -> None:
        app = create_app(_cfg(allowed_invoker_email="admin@example.com"))
        app.config["TESTING"] = True
        pull_results = [PullResult(tab="_Accounts", rows_written=1)]

        with (
            patch("src.auth.google_oidc.verify_token"),
            patch("src.qbo.pull.run_pull", return_value=pull_results),
        ):
            resp = app.test_client().post(
                "/pull", headers={"Authorization": "Bearer fake.jwt.token"}
            )

        assert resp.status_code == 200

    def test_oidc_rejects_invalid_token(self) -> None:
        app = create_app(_cfg(allowed_invoker_email="admin@example.com"))
        app.config["TESTING"] = True

        with patch(
            "src.auth.google_oidc.verify_token",
            side_effect=ValueError("bad token"),
        ):
            resp = app.test_client().post(
                "/pull", headers={"Authorization": "Bearer bad.token"}
            )

        assert resp.status_code == 403
