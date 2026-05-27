# qbo-sync

Cloud Run service that pushes accounting transactions from a Google Sheets workbook into QuickBooks Online (QBO) and pulls reference data from QBO into the workbook on a daily schedule.

See `Sheets-to-QBO_Design_Doc_v0.1.docx` (one folder up) for the full architecture, data model, and milestone plan.

## Status

This repository is at **Milestone 1 (Foundation)**. The Flask app boots, exposes `/health`, and is deployable to Cloud Run. All other routes (`/push`, `/pull`, `/oauth/*`) are stubs that return `501 Not Implemented` — they will be filled in over milestones M2–M9.

## Layout

```
qbo-sync/
├── src/                    Python package: Flask app + modules
│   ├── app.py              Route definitions
│   ├── config.py           Runtime config (env + Secret Manager)
│   ├── auth/               QBO OAuth + Google OIDC verification
│   ├── qbo/                QBO client + pull + push (one module per txn type) + attach
│   ├── sheets/             Sheets API wrapper, row parsers, writers, validation rules
│   ├── drive/              Drive API wrapper (download, move, rename)
│   ├── validators/         Required-field, currency, balance checks
│   └── utils/              Idempotency, secrets, structured logging
├── apps_script/            Workbook-bound Apps Script (clasp-managed)
├── tests/                  pytest unit + integration tests
├── pyproject.toml          Dependencies & metadata (PEP 621)
├── Dockerfile              Container image for Cloud Run
└── deploy.sh               One-line deploy command
```

## Local development

Requires Python 3.11+.

```bash
# Set up venv and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run locally
export FLASK_APP=src.app
export GCP_PROJECT_ID=YOUR_GCP_PROJECT_ID
export ENVIRONMENT=sandbox
flask --app src.app run --port 8080

# Hit the health endpoint
curl http://localhost:8080/health
# {"status":"ok","version":"0.1.0","environment":"sandbox"}

# Run tests
pytest
```

## Deploy to Cloud Run

Prerequisites: `gcloud` CLI installed, authenticated, project set to `YOUR_GCP_PROJECT_ID`, and the APIs enabled (see design doc §2.1).

```bash
./deploy.sh
```

The script:
1. Builds the container image with Cloud Build.
2. Deploys to Cloud Run as service `qbo-sync` in region `us-central1` (override with `REGION=…`).
3. Configures `--no-allow-unauthenticated`, so only authorized invokers can call it.
4. Wires the `qbo-bridge` service account as the runtime identity.

After deploy, the service URL is printed. Update your QBO app's redirect URI to `<URL>/oauth/callback`, then visit `<URL>/oauth/start` once to bootstrap OAuth (M2).

## Environment variables

Read at startup; non-secret values can be set as Cloud Run env vars, secrets are read from Secret Manager.

| Variable | Source | Description |
|---|---|---|
| `GCP_PROJECT_ID` | env | GCP project (e.g., `YOUR_GCP_PROJECT_ID`) |
| `ENVIRONMENT` | env | `sandbox` or `production` |
| `WORKBOOK_ID` | env | Google Sheets file ID for the workbook |
| `DRIVE_INBOX_FOLDER_ID` | env | Drive folder ID for the receipts `_Inbox` |
| `DRIVE_ARCHIVE_ROOT_ID` | env | Drive folder ID for the `Posted/` archive |
| `ALLOWED_INVOKER_EMAIL` | env | The single Google account allowed to invoke `/push` |
| `QBO_CLIENT_ID` | Secret Manager | Intuit Developer app client ID |
| `QBO_CLIENT_SECRET` | Secret Manager | Intuit Developer app client secret |
| `QBO_REFRESH_TOKEN` | Secret Manager | Persisted; rotated on every refresh |
| `QBO_REALM_ID` | Secret Manager | The QBO company ID for the active environment |

## Milestone tracking

| Milestone | Status | Module(s) |
|---|---|---|
| M1: Foundation | **In progress** | `app.py` `/health`, Dockerfile, deploy.sh |
| M2: OAuth round-trip | Not started | `auth/qbo_oauth.py`, `utils/secrets.py` |
| M3: Pull (one tab) | Not started | `qbo/pull.py`, `sheets/writers.py` |
| M4: Pull (all tabs + validation) | Not started | `sheets/validation.py` |
| M5: Push (Bills) | Not started | `qbo/push/bills.py`, `sheets/readers.py`, `validators/common.py` |
| M6: Push (Invoices, Expenses, Sales Receipts) | Not started | corresponding `push/` modules |
| M7: Push (Deposits, Journal Entries) | Not started | corresponding `push/` modules, `validators/balance.py` |
| M8: Attachments | Not started | `drive/client.py`, `qbo/attach.py` |
| M9: Tax & multi-currency hardening | Not started | (cross-cutting) |
| M10: Production cutover | Not started | config flip |

## License

Private — internal tool.
