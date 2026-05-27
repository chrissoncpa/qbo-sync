"""Unit tests for M12: multi-tenant architecture."""

from __future__ import annotations

import datetime
import hashlib
import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

from src.app import create_app
from src.config import Config
from src.models import Company, CompanyContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(multi_tenant: bool = False, admin_api_key: str = "") -> Config:
    return Config(
        project_id="YOUR_GCP_PROJECT_ID",
        environment="sandbox",
        workbook_id="WB-SINGLE",
        drive_inbox_folder_id="",
        drive_archive_root_id="",
        allowed_invoker_email="",
        is_cloud_run=False,
        oauth_redirect_uri="https://example.com/callback",
        flask_secret_key="test",
        multi_tenant=multi_tenant,
        admin_api_key=admin_api_key,
    )


def _company(
    company_id: str = "acme",
    workbook_id: str = "WB-ACME",
    status: str = "active",
    raw_key: str = "testkey123",
) -> Company:
    return Company(
        id=company_id,
        display_name="ACME Corp",
        workbook_id=workbook_id,
        qbo_environment="sandbox",
        api_key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        status=status,
        created_at=datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
    )


def _company_ctx(workbook_id: str = "WB-ACME") -> CompanyContext:
    return CompanyContext(
        project_id="YOUR_GCP_PROJECT_ID",
        company_id="acme",
        workbook_id=workbook_id,
        qbo_environment="sandbox",
        drive_inbox_folder_id="",
        drive_archive_root_id="",
        is_cloud_run=False,
        oauth_redirect_uri="https://example.com/callback",
        flask_secret_key="test",
    )


@pytest.fixture
def single_tenant_client() -> FlaskClient:
    app = create_app(_cfg(multi_tenant=False))
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def multi_tenant_client() -> FlaskClient:
    app = create_app(_cfg(multi_tenant=True, admin_api_key="admin-secret"))
    app.config["TESTING"] = True
    return app.test_client()


# ---------------------------------------------------------------------------
# CompanyContext duck-typing
# ---------------------------------------------------------------------------

class TestCompanyContext:
    def test_secret_suffix_is_company_id(self):
        ctx = _company_ctx()
        assert ctx.secret_suffix == "acme"

    def test_credential_suffix_is_qbo_environment(self):
        ctx = _company_ctx()
        assert ctx.credential_suffix == "sandbox"

    def test_is_sandbox_true_for_sandbox(self):
        ctx = _company_ctx()
        assert ctx.is_sandbox is True

    def test_allowed_invoker_email_is_empty(self):
        ctx = _company_ctx()
        assert ctx.allowed_invoker_email == ""

    def test_environment_property(self):
        ctx = _company_ctx()
        assert ctx.environment == "sandbox"


# ---------------------------------------------------------------------------
# Config new fields
# ---------------------------------------------------------------------------

class TestConfigMultiTenantFields:
    def test_defaults_to_single_tenant(self):
        cfg = _cfg()
        assert cfg.multi_tenant is False
        assert cfg.admin_api_key == ""

    def test_credential_suffix_equals_secret_suffix_in_single_tenant(self):
        cfg = _cfg()
        assert cfg.credential_suffix == cfg.secret_suffix

    def test_multi_tenant_flag(self):
        cfg = _cfg(multi_tenant=True, admin_api_key="k")
        assert cfg.multi_tenant is True
        assert cfg.admin_api_key == "k"


# ---------------------------------------------------------------------------
# POST /companies
# ---------------------------------------------------------------------------

class TestCreateCompany:
    def test_returns_404_in_single_tenant_mode(self, single_tenant_client):
        resp = single_tenant_client.post(
            "/companies",
            data=json.dumps({"company_id": "x", "workbook_id": "y"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_requires_admin_key(self, multi_tenant_client):
        resp = multi_tenant_client.post(
            "/companies",
            data=json.dumps({"company_id": "acme", "workbook_id": "WB1"}),
            content_type="application/json",
            headers={"X-Admin-Key": "wrong"},
        )
        assert resp.status_code == 403

    def test_creates_company_and_returns_api_key(self, multi_tenant_client):
        mock_store = MagicMock()
        with patch("src.db.companies.CompanyStore.create", mock_store):
            with patch("src.db.companies.CompanyStore.__init__", return_value=None):
                resp = multi_tenant_client.post(
                    "/companies",
                    data=json.dumps({
                        "company_id": "acme",
                        "display_name": "ACME Corp",
                        "workbook_id": "WB-ACME",
                        "qbo_environment": "sandbox",
                    }),
                    content_type="application/json",
                    headers={"X-Admin-Key": "admin-secret"},
                )

        assert resp.status_code == 201
        body = resp.get_json()
        assert body["company_id"] == "acme"
        assert body["status"] == "pending_oauth"
        assert "api_key" in body
        assert len(body["api_key"]) > 20

    def test_missing_company_id_returns_400(self, multi_tenant_client):
        resp = multi_tenant_client.post(
            "/companies",
            data=json.dumps({"workbook_id": "WB1"}),
            content_type="application/json",
            headers={"X-Admin-Key": "admin-secret"},
        )
        assert resp.status_code == 400

    def test_missing_workbook_id_returns_400(self, multi_tenant_client):
        resp = multi_tenant_client.post(
            "/companies",
            data=json.dumps({"company_id": "acme"}),
            content_type="application/json",
            headers={"X-Admin-Key": "admin-secret"},
        )
        assert resp.status_code == 400

    def test_invalid_qbo_environment_returns_400(self, multi_tenant_client):
        resp = multi_tenant_client.post(
            "/companies",
            data=json.dumps({"company_id": "acme", "workbook_id": "WB1",
                             "qbo_environment": "staging"}),
            content_type="application/json",
            headers={"X-Admin-Key": "admin-secret"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /push multi-tenant auth
# ---------------------------------------------------------------------------

class TestPushMultiTenantAuth:
    def _base_patches(self, mock_sheets: MagicMock) -> list:
        return [
            patch("src.qbo.client.fetch_secret"),
            patch("src.qbo.client.write_secret_cas"),
            patch("intuitlib.client.AuthClient"),
            patch("quickbooks.QuickBooks"),
            patch("src.sheets.client.SheetsClient.from_credentials", return_value=mock_sheets),
            patch("src.sheets.writers.append_log"),
            patch("src.sheets.writers.write_row_status"),
            patch("src.sheets.readers.read_bills",           return_value=[]),
            patch("src.sheets.readers.read_invoices",        return_value=[]),
            patch("src.sheets.readers.read_expenses",        return_value=[]),
            patch("src.sheets.readers.read_sales_receipts",  return_value=[]),
            patch("src.sheets.readers.read_deposits",        return_value=[]),
            patch("src.sheets.readers.read_journal_entries", return_value=[]),
        ]

    def test_push_without_api_key_returns_401(self, multi_tenant_client):
        resp = multi_tenant_client.post("/push", data="{}", content_type="application/json")
        assert resp.status_code == 401

    def test_push_with_invalid_api_key_returns_401(self, multi_tenant_client):
        mock_store = MagicMock()
        mock_store.get_by_api_key.return_value = None

        with patch("src.db.companies.CompanyStore.__init__", return_value=None):
            with patch("src.db.companies.CompanyStore.get_by_api_key",
                       return_value=None):
                resp = multi_tenant_client.post(
                    "/push",
                    data="{}",
                    content_type="application/json",
                    headers={"X-Api-Key": "bad-key"},
                )
        assert resp.status_code == 401

    def test_push_with_suspended_company_returns_401(self, multi_tenant_client):
        suspended = _company(status="suspended")
        with patch("src.db.companies.CompanyStore.__init__", return_value=None):
            with patch("src.db.companies.CompanyStore.get_by_api_key",
                       return_value=suspended):
                resp = multi_tenant_client.post(
                    "/push",
                    data="{}",
                    content_type="application/json",
                    headers={"X-Api-Key": "testkey123"},
                )
        assert resp.status_code == 401

    def test_push_with_valid_api_key_uses_company_workbook(self, multi_tenant_client):
        mock_sheets = MagicMock()
        mock_sheets.read_tab.return_value = []
        company = _company(workbook_id="WB-ACME", status="active")

        with ExitStack() as stack:
            for p in self._base_patches(mock_sheets):
                stack.enter_context(p)
            stack.enter_context(
                patch("src.db.companies.CompanyStore.__init__", return_value=None)
            )
            stack.enter_context(
                patch("src.db.companies.CompanyStore.get_by_api_key", return_value=company)
            )
            resp = multi_tenant_client.post(
                "/push",
                data="{}",
                content_type="application/json",
                headers={"X-Api-Key": "testkey123"},
            )

        assert resp.status_code == 200
        # Confirm the company's workbook was read, not the service-level WB-SINGLE
        calls = [str(c) for c in mock_sheets.read_tab.call_args_list]
        assert any("WB-ACME" in c for c in calls)

    def test_single_tenant_push_still_works(self, single_tenant_client):
        mock_sheets = MagicMock()
        mock_sheets.read_tab.return_value = []

        with ExitStack() as stack:
            for p in self._base_patches(mock_sheets):
                stack.enter_context(p)
            resp = single_tenant_client.post("/push", data="{}", content_type="application/json")

        assert resp.status_code == 200
