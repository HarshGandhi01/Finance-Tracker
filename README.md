# Am I cooked?

A personal finance tracker with a dark Streamlit dashboard.

**ICICI SMS → MacroDroid → FastAPI webhook → SQLAlchemy database → Streamlit dashboard**

`index.py` authenticates webhook requests and parses messages with `sms_parser.py`.
`db.py` stores transactions in Neon Postgres in production and SQLite locally.
`dashboard/app.py` provides Overview and Settings pages, including splits, repayments,
vendor rules, category management, and food-budget tracking.

## Configuration

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Production Postgres connection URL, including SSL options. Leave unset or empty for SQLite. |
| `COOKED_TOKEN` | Required webhook token, sent by MacroDroid in the `x-token` header. |
| `COOKED_DB` | Optional local SQLite path; defaults to `cooked.db`. |

Set environment variables before starting the app. Streamlit Cloud also exports
top-level string values in its Secrets settings as environment variables.
`.env.example` is a reference; the app does not automatically load `.env` files.
The dashboard has no login, by design; no `DASHBOARD_PASSWORD` is used.
Keep local secrets in `.streamlit/secrets.toml`, which is excluded from Git.

## Run locally

Use Python 3.12. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
$env:DATABASE_URL = ""
$env:COOKED_DB = "cooked.db"
$env:COOKED_TOKEN = "replace-with-a-private-token"
python -m uvicorn index:app --reload
```

In another activated terminal, with the same database environment:

```powershell
python -m streamlit run dashboard/app.py
```

On macOS/Linux, activate with `source .venv/bin/activate` and use `export NAME=value`
instead of PowerShell's `$env:NAME = "value"`.

To import a local statement, install `requirements-tools.txt`, set the PDF path in
`import_statement.py`, and run that script against the intended database.

## Tests

```powershell
python -m pytest -q
```

Tests use disposable SQLite databases. They cover budget calculations, SMS parsing,
deduplication, concurrent rollover, categories, and Streamlit interactions.
Dependency versions are pinned to the versions used for local verification.

## Deploy

**Webhook:** deploy the repository's FastAPI app (`index:app`) to the existing Vercel
Python project, or run it with Uvicorn on a Python host. Set `DATABASE_URL` to Neon
and set `COOKED_TOKEN`. Configure MacroDroid to POST the SMS as plain text or
`{"sms": "..."}` to the webhook URL with the `x-token` header. `GET /` is a health check.

**Dashboard:** on Streamlit Community Cloud, choose `dashboard/app.py` as the entrypoint,
Python 3.12, and the repository root as the working directory. Streamlit uses
`dashboard/requirements.txt`; put `DATABASE_URL` in the app's Secrets settings.
The root `.streamlit/config.toml` supplies the dark theme. Redeploy/reboot after
updating dependencies. The keep-awake workflow needs no dashboard password.

Startup runs additive, idempotent migrations through `init_db()`. Existing transaction
columns and data are preserved. Category seeding runs once; deleted categories and
funds are not recreated on later restarts.

## Budget behavior

- Daily allowance is `(balance − reserved funds) / days to cover`.
- Food left today is today's ₹350 budget minus today's personal food spending,
  floored at zero. The silo is shown separately and is already part of cash.
- Comfortable means at least ₹437.50/day; Tight means ₹350–437.49; Cooked means below ₹350.
- Food, Pocket Money, and Other are locked categories. Deleting another category
  moves its transactions and vendor rules to a chosen replacement. You can either
  move its sinking fund (combining reservations) or delete that fund too.
- Identical SMS text is deduplicated for ten minutes; UPI references remain unique.
