# Sports Hub

## Features
- Product catalog with variants, tags, tiered pricing, and CSV import/export
- Inventory management with warehouses, bins, batches, FEFO picking, and reservations
- Pricing rules and effective price calculations
- Unified search across products, news, and assessment questions
- News ingestion with quarantine and admin review
- Assessments with assignments, submissions, auto-grading, and trainer grading
- Admin dashboards for anomalies, audit log, and user management
- HMAC-signed mutating requests and JWT auth

## Quick Start
1. cp .env.example .env
   - Before starting the app, replace the placeholder secrets in `.env` with secure random values (the app will refuse to start if they remain unchanged).
2. docker compose up --build
3. Open http://localhost:5000
4. Login: admin / <your-custom-ADMIN_PASSWORD>

## Local Development (without Docker)
1. `python3 -m venv venv && source venv/bin/activate`
2. `pip install -r requirements.txt`
3. `cp .env.example .env.local`
4. `export $(cat .env.local | xargs) && export FLASK_APP=app:create_app`
5. `flask db-init && flask run`
6. Open http://localhost:5000 — Login: admin / <your-custom-ADMIN_PASSWORD>
 7. Because `_hmac_key` relies on a SameSite cookie that is secure by default, the local dev server runs over HTTP so the cookie is set with `secure=False`. If you switch to HTTPS locally (via a reverse proxy or TLS), the cookie will honor the `secure` flag and only send over HTTPS.

## Commands
- Run tests: `./run_tests.sh`
- Ingest news: `flask ingest-news`
- Cleanup nonces: `flask cleanup-nonces`

## Verification Checklist
- Create a product with tiered pricing and verify effective price
- Create warehouse/bin/batch and validate FEFO pick order
- Run stock count with >2% variance and confirm reason required
- Save a search and toggle pinned state
- Ingest a sample RSS/JSON file and confirm news appears

## Known Limitations
- **SQLite Concurrency**: SQLite does not support row-level locking. The reservation system uses `begin_nested()` (savepoints) to prevent data corruption but does not guarantee serializable isolation under heavy concurrent load. For high-traffic production, consider PostgreSQL.
- **HMAC Cookie**: The `_hmac_key` cookie is set with `httponly=False` to enable client-side HMAC signing. This is a documented, accepted trade-off. XSS mitigations (bleach sanitization, output encoding, SameSite=Strict) are in place.
- **Scheduler Duplication**: Running Gunicorn with multiple workers may duplicate APScheduler jobs. Use `--workers 1` or switch to an external scheduler (e.g., cron) for multi-worker deployments.

## Security Maintenance
- Rotate HMAC keys periodically: `flask rotate-hmac-keys` (users must re-login after rotation)
- Rotate secrets in `.env` / `.env.local` regularly
- Never commit `.env` or `.env.local` to version control (both are in `.gitignore`)
