# Sports Hub

**Type:** Full-stack web application (Flask + HTMX, server-rendered templates)

## Features
- Product catalog with variants, tags, tiered pricing, and CSV import/export
- Inventory management with warehouses, bins, batches, FEFO picking, and reservations
- Pricing rules and effective price calculations with booking-window enforcement
- Unified search across products, news, and assessment questions
- News ingestion with quarantine and admin review
- Assessments with assignments, submissions, auto-grading, and trainer grading
- Admin dashboards for anomalies, audit log, and user management
- Server-side HMAC-SHA256 request signing via `/auth/sign` and JWT auth

## Quick Start (Docker — Demo/Evaluation)
1. From this directory (`repo/`), copy environment defaults: `cp .env.example .env` (Compose loads `.env`; without this file, `docker compose` will fail.)
2. `docker compose up --build`
3. Open http://localhost:5000 — you should see the Sports Hub login page
4. Login: `admin` / `DemoAdmin2026Secure!` — you should land on the dashboard
5. To create demo accounts for all roles: `docker compose exec web flask seed-demo-users`

The `.env.example` ships with `DEMO_MODE=true`, which allows the app to start with demo secrets for evaluation. A prominent warning is logged on startup.

### Demo Credentials (all roles)

| Role | Username | Password |
|---|---|---|
| `admin` | `admin` | `DemoAdmin2026Secure!` |
| `content_editor` | `demo_editor` | `DemoEditor2026!` |
| `inventory_manager` | `demo_inventory` | `DemoInventory2026!` |
| `trainer` | `demo_trainer` | `DemoTrainer2026!` |
| `staff` | `demo_staff` | `DemoStaff2026!` |

`seed-demo-users` is idempotent — safe to run multiple times.

## Quick Start (Docker — Production)
1. `cp .env.example .env`
2. Replace all secrets with secure random values and remove `DEMO_MODE` (or set to `false`)
3. `docker compose up --build` (Compose uses `env_file: .env` by default.)
4. Open http://localhost:5000 — Login: `admin` / your `ADMIN_PASSWORD`

Without `DEMO_MODE=true`, the app refuses to start if it detects demo-prefixed secrets or known weak placeholders.

## Local Development (without Docker)

> **Note:** This path is for contributors only. For evaluation or demos, use the Docker path above.

1. `python3 -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. `cp .env.example .env.local` and edit the values (replace demo secrets with secure random strings — use `openssl rand -hex 32` for each secret)
4. `export $(cat .env.local | xargs) && export FLASK_APP=app:create_app`
5. `flask db-init && flask run`
6. Open http://localhost:5000 — Login: `admin` / your `ADMIN_PASSWORD`

## Commands
- Run tests in Docker: `./run_tests.sh` (builds the image and runs pytest; all tests should report PASSED)
- Run tests locally (no Docker), from `repo/` with the same env vars as tests expect:
  ```bash
  export SECRET_KEY=test-secret-key-for-testing JWT_SECRET_KEY=test-jwt-secret-for-testing \
    HMAC_SECRET=test-hmac-secret ADMIN_PASSWORD=SecureTestPass123!
  python -m pytest unit_tests/ API_tests/ -v --tb=short
  ```
- Seed demo users: `flask seed-demo-users`
- Ingest news: `flask ingest-news`
- Cleanup nonces: `flask cleanup-nonces`
- Rotate HMAC keys: `flask rotate-hmac-keys` (users must re-login after rotation)

## Security Model
- **Authentication**: Username/password with minimum 12 characters, salted scrypt hashing, account lockout after 5 failed attempts for 15 minutes.
- **Sessions**: Short-lived JWT access tokens (30 min) stored in cookies, with refresh tokens capped at an absolute 8-hour session ceiling.
- **HMAC Signing**: All mutating API requests require HMAC-SHA256 signatures. HMAC keys are stored server-side (encrypted with Fernet at rest) and never exposed to the client. The `/auth/sign` endpoint generates signatures server-side; the client calls this endpoint before submitting mutating requests.
- **Anti-Replay**: Each signed request includes a nonce and timestamp. Nonces are stored for 24 hours to prevent replay; timestamp skew is limited to ±5 minutes.
- **CSRF Protection**: Flask-WTF CSRF is enabled globally (`WTF_CSRF_ENABLED`, default on). HTMX requests include the CSRF token via a global `hx-headers` attribute on `<body>`. The `/auth/sign` endpoint validates CSRF tokens on all requests.
- **JWT cookies**: `JWT_COOKIE_CSRF_PROTECT` (default on), `JWT_COOKIE_SECURE` (set `true` behind HTTPS), and `JWT_COOKIE_SAMESITE` (default `Lax`) are configurable via environment — see `repo/app/config.py` and `.env.example`.
- **Rate Limiting**: 60 requests/minute per authenticated user (keyed by JWT identity). Default storage is explicit in-memory (`RATELIMIT_STORAGE_URI=memory://`); set a Redis URI in production for multi-worker consistency.
- **Anomaly Detection**: Rule-based alerts for repeated failed logins, rapid search bursts, and frequent reservation holds, recorded in `AnomalyAlert` and `AuditLog` tables for admin review.
- **Sensitive Data**: HMAC keys encrypted with Fernet at rest; audit log IP addresses hashed with SHA-256 before storage.

## Verification Checklist
- Create a product with tiered pricing and verify effective price
- Create warehouse/bin/batch and validate FEFO pick order
- Run stock count with >2% variance and confirm reason required
- Save a search and toggle pinned state
- Ingest a sample RSS/JSON file and confirm news appears
- Request a quote via `/pricing/calculate` with a too-soon booking time and confirm 400 rejection

## Known Limitations
- **SQLite Concurrency**: SQLite does not support row-level locking. The reservation system uses `begin_nested()` (savepoints) with optimistic locking (`version_id_col`) and `busy_timeout=5000` to handle concurrent writes gracefully. For high-traffic production, consider PostgreSQL.
- **Scheduler Duplication**: Running Gunicorn with multiple workers may duplicate APScheduler jobs. Use `--workers 1` or switch to an external scheduler (e.g., cron) for multi-worker deployments.
- **Browser Crypto Requirement for Secure File Uploads**: Multipart HMAC signing uses `window.crypto.subtle` to hash file bytes before submit. Browsers without WebCrypto support cannot complete signed file-upload forms and will receive an in-UI warning.

## Security Maintenance
- Rotate HMAC keys periodically: `flask rotate-hmac-keys` (users must re-login after rotation)
- Rotate secrets in `.env` / `.env.local` regularly
- Never commit `.env` or `.env.local` to version control (both are in `.gitignore`)
