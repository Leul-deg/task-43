# Test Coverage Report

## Tests Check

**Project shape:** Full-stack Flask application with server-rendered HTMX templates. Appropriate test categories: unit tests, API/integration tests, HTMX integration tests, and cross-module E2E workflow tests. No frontend component tests required given the server-rendering approach.

**Categories present (post gap-filling):**

| Category | Files | Functions | Status |
|---|---|---|---|
| Unit tests | 8 files (auth, products, inventory, pricing, news, assessments, security, cli) | ~59 | Substantive |
| API/integration tests | 9 files (auth, products, pricing, inventory, search, news, assessments, admin, HTMX) | ~85 | Substantive |
| E2E workflow tests | 1 file | 3 | Present, lightweight |
| **Total** | **17 files** | **~148** | |

**run_tests.sh:** Cleanly Dockerized. Builds image, runs unit tests then API tests inside Docker containers with fixed test secrets. No local Python or Node dependency. Passes inspection.

**Transport layer:** Flask test client hits real routes backed by in-memory SQLite — no mocked transport. API tests exercise genuine request/response paths with DB assertions.

**Gap remediation results:**

- **Products** (3→12 API tests): Now covers detail view, publish toggle + role guard, delete/unpublish, variant add with duplicate-SKU rejection, variant update, tiered pricing creation with DB assertion, sort-by-name, and compound price+category filter.
- **Pricing** (0→9 dedicated API tests, new file): Full rule CRUD with role guards; discount, markup, expired-rule-not-applied, and compound discount+markup all verified with JSON payload assertions on `unit_price` and `total`.
- **Assessments** (2→7 unit tests): Adds update, publish toggle, full question CRUD cycle, and two IDOR tests (staff cannot view another staff's results, staff cannot start another's assignment).
- **Search** (7→10 tests): Three compound filter tests (price+category, price+tag, category+tag) seeded in single app context to avoid cross-context object issues.
- **News** (8→14 API tests): Quarantine delete, quarantine release (DB record removal verified), role guards on both, source update, and non-admin source update rejection.

---

## Test Coverage Score: 87 / 100

## Score Rationale

The suite is now genuinely comprehensive across all eight major modules. Core business logic (FEFO, concurrency-safe reservations, dynamic pricing, assessment grading) is tested with DB-level assertions. Security surface (HMAC, CSRF, IDOR, account lockout, anomaly detection) is explicitly covered. The newly added pricing API tests assert exact `unit_price`/`total` JSON values, not just status codes. The score is held below 90 because three genuine gaps remain: the `PUT /products/<id>` update endpoint is never exercised at the API layer despite being a real HMAC-guarded route; mixed-type assessment submissions (MC + short-answer in the same attempt) are not tested; and admin audit-log date-range filtering is untested. The E2E suite remains thin (3 workflows), though this is partially offset by the depth of the unit and API layers.

## Key Gaps

1. **`PUT /products/<id>` update endpoint untested at API layer** — the route has role guards, HMAC validation, tag management, and image validation; it is only covered by source inspection, not by a running test
2. **Mixed question-type assessment submission** — a submission with both `multiple_choice` and `short_answer` questions in the same assessment is not tested; the conditional auto-grade/pending-grade split behavior is only tested for pure-type assessments
3. **Admin audit-log date-range filter** — action filter is covered, but date-range filtering of the audit log is untested at the API layer
4. **E2E coverage remains thin** — three cross-module workflows cover the main happy paths; no E2E workflow exercises the admin quarantine-review-then-re-ingest pipeline end to end
