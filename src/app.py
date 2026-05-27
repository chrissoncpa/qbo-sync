"""Flask application factory."""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify, redirect, request, session

from src import __version__
from src.config import Config

log = logging.getLogger(__name__)


def create_app(config: Config | None = None) -> Flask:
    cfg = config or Config.from_env()
    app = Flask(__name__)
    app.config["QBO_SYNC_CONFIG"] = cfg
    app.secret_key = cfg.flask_secret_key

    _configure_logging(cfg)
    _register_routes(app, cfg)

    log.info("qbo-sync %s booted in %s mode", __version__, cfg.environment)
    if not cfg.is_sandbox and not cfg.allowed_invoker_email:
        log.warning(
            "SECURITY: running in production without ALLOWED_INVOKER_EMAIL — "
            "/push and /pull are unauthenticated"
        )
    return app


def _configure_logging(cfg: Config) -> None:
    """Wire up structured logging.

    In Cloud Run, google-cloud-logging is set up to emit JSON to stdout, which
    Cloud Logging picks up automatically. Locally, we use a plain stream handler.
    """
    if cfg.is_cloud_run:
        try:
            import google.cloud.logging  # type: ignore[import-untyped]

            client = google.cloud.logging.Client()
            client.setup_logging(log_level=logging.INFO)
            return
        except Exception as exc:  # pragma: no cover - best-effort
            log.warning("Falling back to stdlib logging: %s", exc)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _register_routes(app: Flask, cfg: Config) -> None:
    @app.get("/health")
    def health() -> tuple[dict[str, str], int]:
        return jsonify(
            status="ok",
            version=__version__,
            environment=cfg.environment,
            project=cfg.project_id,
            auth_required=bool(cfg.allowed_invoker_email),
        ), 200

    @app.get("/readyz")
    def readyz() -> tuple[dict[str, Any], int]:
        issues: list[str] = []
        if not cfg.workbook_id:
            issues.append("WORKBOOK_ID not configured")
        if not cfg.oauth_redirect_uri:
            issues.append("OAUTH_REDIRECT_URI not configured")
        if issues:
            return jsonify(status="not_ready", issues=issues), 503
        return jsonify(status="ok"), 200

    @app.post("/companies")
    def create_company() -> tuple[dict[str, Any], int]:
        import datetime
        import hashlib
        import secrets as _secrets

        from src.db.companies import CompanyStore
        from src.models import Company

        if not cfg.multi_tenant:
            return jsonify(error="not_found"), 404

        if not cfg.admin_api_key:
            return jsonify(error="admin key not configured"), 500

        given_key = request.headers.get("X-Admin-Key", "")
        if given_key != cfg.admin_api_key:
            return jsonify(error="unauthorized"), 403

        body = request.get_json(silent=True) or {}
        company_id = body.get("company_id", "")
        display_name = body.get("display_name", "")
        workbook_id = body.get("workbook_id", "")
        qbo_environment = body.get("qbo_environment", "sandbox")

        if not company_id or not isinstance(company_id, str):
            return jsonify(error="'company_id' is required"), 400
        if not workbook_id or not isinstance(workbook_id, str):
            return jsonify(error="'workbook_id' is required"), 400
        if qbo_environment not in ("sandbox", "production"):
            return jsonify(error="'qbo_environment' must be 'sandbox' or 'production'"), 400

        raw_key = _secrets.token_urlsafe(32)
        company = Company(
            id=company_id,
            display_name=display_name or company_id,
            workbook_id=workbook_id,
            qbo_environment=qbo_environment,
            api_key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
            status="pending_oauth",
            created_at=datetime.datetime.now(datetime.timezone.utc),
            drive_inbox_folder_id=body.get("drive_inbox_folder_id", ""),
            drive_archive_root_id=body.get("drive_archive_root_id", ""),
        )
        store = CompanyStore(cfg.project_id)
        store.create(company)
        log.info("company provisioned: %s", company_id)
        return jsonify(
            company_id=company_id,
            api_key=raw_key,
            status="pending_oauth",
        ), 201

    @app.post("/push")
    def push() -> tuple[dict[str, Any], int]:
        import datetime

        from src.auth.google_oidc import verify_token
        from src.qbo.client import get_qbo_client
        from src.drive.client import DriveClient
        from src.qbo.attach import attach_file_to_transaction
        from src.qbo.push.bills import push_bill
        from src.qbo.push.invoices import push_invoice
        from src.qbo.push.expenses import push_expense
        from src.qbo.push.sales_receipts import push_sales_receipt
        from src.qbo.push.deposits import push_deposit
        from src.qbo.push.journal_entries import push_journal_entry
        from src.sheets.client import SheetsClient
        from src.sheets.readers import (
            read_bills, read_invoices, read_expenses,
            read_sales_receipts, read_deposits, read_journal_entries,
        )
        from src.sheets.writers import append_log, write_row_status
        from src.validators.common import ValidationError

        from src.auth.api_key import resolve_company_context

        # Determine the effective config: single-tenant uses cfg directly;
        # multi-tenant resolves a CompanyContext from the X-Api-Key header.
        if cfg.multi_tenant:
            eff_cfg = resolve_company_context(request.headers, cfg)
            if eff_cfg is None:
                return jsonify(error="unauthorized"), 401
        else:
            eff_cfg = cfg  # type: ignore[assignment]
            if cfg.allowed_invoker_email:
                auth_header = request.headers.get("Authorization", "")
                if not auth_header.startswith("Bearer "):
                    return jsonify(error="missing_auth"), 401
                try:
                    verify_token(auth_header.removeprefix("Bearer "), cfg.allowed_invoker_email)
                except ValueError as exc:
                    log.warning("push: OIDC verification failed: %s", exc)
                    return jsonify(error="unauthorized"), 403

        if not eff_cfg.workbook_id:
            return jsonify(error="WORKBOOK_ID not configured"), 500

        # Parse optional row selection: {"selection": [{"tab": "Bills", "rows": [3,4]}]}
        # Absent or missing "selection" key → push all eligible rows (backward compatible).
        body = request.get_json(silent=True) or {}
        raw_selection = body.get("selection")
        selection_map: dict[str, set[int]] | None = None
        if raw_selection is not None:
            if not isinstance(raw_selection, list):
                return jsonify(error="'selection' must be a list"), 400
            selection_map = {}
            for entry in raw_selection:
                if not isinstance(entry, dict):
                    return jsonify(error="each selection entry must be an object"), 400
                tab = entry.get("tab")
                rows_list = entry.get("rows")
                if not isinstance(tab, str) or not isinstance(rows_list, list):
                    return jsonify(error="selection entry must have string 'tab' and list 'rows'"), 400
                try:
                    selection_map[tab] = {int(r) for r in rows_list}
                except (TypeError, ValueError):
                    return jsonify(error="'rows' must be a list of integers"), 400

        sheets = SheetsClient.from_credentials()
        qb = get_qbo_client(eff_cfg)
        drive = DriveClient.from_credentials() if eff_cfg.drive_inbox_folder_id else None

        _TAB_TO_QBO_TYPE = {
            "Bills": "Bill",
            "Invoices": "Invoice",
            "Expenses": "Purchase",
            "Sales Receipts": "SalesReceipt",
            "Deposits": "Deposit",
        }

        ref_data = {
            "vendors":     sheets.read_tab(eff_cfg.workbook_id, "_Vendors"),
            "accounts":    sheets.read_tab(eff_cfg.workbook_id, "_Accounts"),
            "classes":     sheets.read_tab(eff_cfg.workbook_id, "_Classes"),
            "departments": sheets.read_tab(eff_cfg.workbook_id, "_Departments"),
            "customers":   sheets.read_tab(eff_cfg.workbook_id, "_Customers"),
            "items":       sheets.read_tab(eff_cfg.workbook_id, "_Items"),
            "terms":       sheets.read_tab(eff_cfg.workbook_id, "_Terms"),
        }

        _PUSH_PIPELINE = [
            (read_bills,          push_bill,          "Bills"),
            (read_invoices,       push_invoice,       "Invoices"),
            (read_expenses,       push_expense,       "Expenses"),
            (read_sales_receipts, push_sales_receipt, "Sales Receipts"),
            (read_deposits,       push_deposit,       "Deposits"),
        ]

        posted = errored = skipped = 0
        total_rows = 0

        for reader, pusher, tab_name in _PUSH_PIPELINE:
            rows = reader(sheets, eff_cfg.workbook_id)
            if selection_map is not None:
                allowed = selection_map.get(tab_name, set())
                rows = [r for r in rows if r["_sheet_row"] in allowed]
            total_rows += len(rows)
            for row in rows:
                sheet_row = row["_sheet_row"]
                status_col = row["_status_col"]
                now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                try:
                    saved = pusher(row, ref_data, qb)
                    write_row_status(sheets, eff_cfg.workbook_id, tab_name, sheet_row, status_col,
                                     "posted", saved.Id, now)
                    posted += 1
                    if drive and row.get("Attachment", "").strip():
                        try:
                            attach_file_to_transaction(
                                row["Attachment"].strip(),
                                saved.Id,
                                _TAB_TO_QBO_TYPE[tab_name],
                                qb, drive,
                                eff_cfg.drive_inbox_folder_id,
                                eff_cfg.drive_archive_root_id,
                            )
                        except Exception as att_exc:
                            log.warning("attachment failed row %d: %s", sheet_row, att_exc)
                except ValidationError as exc:
                    write_row_status(sheets, eff_cfg.workbook_id, tab_name, sheet_row, status_col,
                                     f"error: {exc}")
                    log.warning("push: validation error row %d: %s", sheet_row, exc)
                    errored += 1
                except Exception as exc:
                    write_row_status(sheets, eff_cfg.workbook_id, tab_name, sheet_row, status_col,
                                     f"error: {exc}")
                    log.exception("push: unexpected error row %d", sheet_row)
                    errored += 1

        je_allowed: set[int] | None = (
            selection_map.get("Journal Entries") if selection_map is not None else None
        )
        for group in read_journal_entries(sheets, eff_cfg.workbook_id):
            if je_allowed is not None and not any(r in je_allowed for r in group["_sheet_rows"]):
                continue
            total_rows += 1
            status_col = group["_status_col"]
            now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                saved = push_journal_entry(group, ref_data, qb)
                for sheet_row in group["_sheet_rows"]:
                    write_row_status(sheets, eff_cfg.workbook_id, "Journal Entries",
                                     sheet_row, status_col, "posted", saved.Id, now)
                posted += 1
            except ValidationError as exc:
                for sheet_row in group["_sheet_rows"]:
                    write_row_status(sheets, eff_cfg.workbook_id, "Journal Entries",
                                     sheet_row, status_col, f"error: {exc}")
                log.warning("push: JE validation error %s: %s", group.get("RefNumber"), exc)
                errored += 1
            except Exception as exc:
                for sheet_row in group["_sheet_rows"]:
                    write_row_status(sheets, eff_cfg.workbook_id, "Journal Entries",
                                     sheet_row, status_col, f"error: {exc}")
                log.exception("push: unexpected JE error %s", group.get("RefNumber"))
                errored += 1

        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        append_log(sheets, eff_cfg.workbook_id, now, "push",
                   "selected" if selection_map is not None else "all",
                   total_rows, posted, errored, skipped)
        log.info("push complete: %d posted, %d errored, %d skipped", posted, errored, skipped)
        return jsonify(status="ok", posted=posted, errored=errored, skipped=skipped), 200

    @app.post("/pull")
    def pull() -> tuple[dict[str, Any], int]:
        from src.auth.api_key import resolve_company_context
        from src.auth.google_oidc import verify_token
        from src.qbo.pull import run_pull

        if cfg.multi_tenant:
            eff_cfg = resolve_company_context(request.headers, cfg)
            if eff_cfg is None:
                return jsonify(error="unauthorized"), 401
        else:
            eff_cfg = cfg  # type: ignore[assignment]
            if cfg.allowed_invoker_email:
                auth_header = request.headers.get("Authorization", "")
                if not auth_header.startswith("Bearer "):
                    return jsonify(error="missing_auth"), 401
                try:
                    verify_token(auth_header.removeprefix("Bearer "), cfg.allowed_invoker_email)
                except ValueError as exc:
                    log.warning("pull: OIDC verification failed: %s", exc)
                    return jsonify(error="unauthorized"), 403

        if not eff_cfg.workbook_id:
            return jsonify(error="WORKBOOK_ID not configured"), 500

        results = run_pull(eff_cfg)
        summary = {r.tab: r.rows_written for r in results}
        log.info("pull complete: %s", summary)
        return jsonify(status="ok", tabs=summary), 200

    @app.get("/oauth/start")
    def oauth_start() -> object:
        from src.auth.qbo_oauth import start_authorization_url

        if not cfg.oauth_redirect_uri:
            return jsonify(error="OAUTH_REDIRECT_URI not configured"), 500

        if cfg.multi_tenant:
            # Admin must provide X-Admin-Key and ?company_id=<id>
            if request.headers.get("X-Admin-Key", "") != cfg.admin_api_key or not cfg.admin_api_key:
                return jsonify(error="unauthorized"), 403
            company_id = request.args.get("company_id", "")
            if not company_id:
                return jsonify(error="company_id is required"), 400
            from src.db.companies import CompanyStore
            from src.models import CompanyContext
            company = CompanyStore(cfg.project_id).get(company_id)
            if not company:
                return jsonify(error="company not found"), 404
            eff_cfg: Any = CompanyContext(
                project_id=cfg.project_id,
                company_id=company.id,
                workbook_id=company.workbook_id,
                qbo_environment=company.qbo_environment,
                drive_inbox_folder_id=company.drive_inbox_folder_id,
                drive_archive_root_id=company.drive_archive_root_id,
                is_cloud_run=cfg.is_cloud_run,
                oauth_redirect_uri=cfg.oauth_redirect_uri,
                flask_secret_key=cfg.flask_secret_key,
            )
            session["oauth_company_id"] = company_id
        else:
            eff_cfg = cfg

        url, state = start_authorization_url(eff_cfg)
        session["oauth_state"] = state
        return redirect(url)

    @app.get("/oauth/callback")
    def oauth_callback() -> tuple[dict[str, str], int]:
        from src.auth.qbo_oauth import exchange_code

        error = request.args.get("error")
        if error:
            log.warning("OAuth callback received error from Intuit: %s", error)
            return jsonify(error="oauth_denied", detail=error), 400

        code = request.args.get("code")
        state = request.args.get("state")
        realm_id = request.args.get("realmId")

        if not code or not state or not realm_id:
            return jsonify(error="missing_params"), 400

        expected_state = session.pop("oauth_state", None)
        if state != expected_state:
            return jsonify(error="state_mismatch"), 400

        if cfg.multi_tenant:
            company_id = session.pop("oauth_company_id", None)
            if not company_id:
                return jsonify(error="session expired — restart oauth flow"), 400
            from src.db.companies import CompanyStore
            from src.models import CompanyContext
            company = CompanyStore(cfg.project_id).get(company_id)
            if not company:
                return jsonify(error="company not found"), 404
            eff_cfg: Any = CompanyContext(
                project_id=cfg.project_id,
                company_id=company.id,
                workbook_id=company.workbook_id,
                qbo_environment=company.qbo_environment,
                drive_inbox_folder_id=company.drive_inbox_folder_id,
                drive_archive_root_id=company.drive_archive_root_id,
                is_cloud_run=cfg.is_cloud_run,
                oauth_redirect_uri=cfg.oauth_redirect_uri,
                flask_secret_key=cfg.flask_secret_key,
            )
        else:
            eff_cfg = cfg

        token_set = exchange_code(eff_cfg, code, realm_id)

        if cfg.multi_tenant:
            CompanyStore(cfg.project_id).update_status(company_id, "active")

        log.info("OAuth bootstrap complete for realm %s", token_set.realm_id)
        return jsonify(status="ok", realm_id=token_set.realm_id), 200

    @app.errorhandler(404)
    def not_found(_e: Exception) -> tuple[dict[str, str], int]:
        return jsonify(error="not_found"), 404

    @app.errorhandler(500)
    def server_error(e: Exception) -> tuple[dict[str, str], int]:  # pragma: no cover
        log.exception("Unhandled error: %s", e)
        return jsonify(error="internal_error"), 500


# Allow `flask --app src.app run` to find an app instance, in addition to the
# factory used by gunicorn.  Skip at import time if required env vars are
# absent (e.g. during pytest collection before fixtures inject them).
try:
    app = create_app()
except RuntimeError:
    app = None  # type: ignore[assignment]


if __name__ == "__main__":  # pragma: no cover
    create_app().run(host="0.0.0.0", port=8080)
