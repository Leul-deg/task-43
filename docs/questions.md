# Questions & Clarifications

## Q1: Database Choice
**Q:** The prompt specifies SQLite for offline-first local operation. Should PostgreSQL or other databases also be supported?
**A:** No. SQLite only, consistent with the on-prem offline-first requirement. WAL mode enabled for concurrent read/write support.

## Q2: HMAC Key Delivery to Client
**Q:** HMAC-SHA256 request signing requires the client-side JavaScript to access the user's HMAC key. httpOnly cookies block JS access. How should the key be delivered?
**A:** Non-httpOnly cookie with SameSite=Strict. This is an accepted design trade-off documented in code. XSS mitigations (bleach sanitization, output encoding) reduce the risk surface.

## Q3: Database Migrations
**Q:** Should Alembic be integrated for schema migrations on existing databases?
**A:** Deferred. Current delivery uses `db.create_all()` for initial setup. Documented as a known limitation in README. For production upgrades, manual migration scripts would be needed.

## Q4: Multi-Worker Scheduler Duplication
**Q:** APScheduler jobs (reservation release, nonce cleanup, news ingestion) will duplicate across Gunicorn workers. Should this be addressed?
**A:** Documented as a known limitation. Recommendation: run Gunicorn with a single worker, or move scheduled tasks to an external cron/systemd timer for multi-worker deployments.

## Q5: Frontend Framework
**Q:** The prompt says "without a heavy frontend framework." Should any client-side JavaScript framework be used?
**A:** No. Server-rendered HTML with HTMX for dynamic partial updates and Bootstrap 5 for styling. Only custom JS is the HMAC signing script (`hmac.js`).

## Q6: Image Upload Constraints
**Q:** What file types and size limits should apply to product image uploads?
**A:** Allowed: jpg, jpeg, png, gif, webp. Maximum size: 5 MB per file. Validated on upload with descriptive error messages.

## Q7: Reservation Business Logic
**Q:** When a held reservation expires, should stock be "returned"?
**A:** No. Holds only reduce the calculated available stock — they do not deduct physical batch quantities. Only confirmed reservations deduct from batches (FEFO order). Releasing a hold simply changes the reservation status, which automatically frees up the available count.
