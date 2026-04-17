# Sports Hub — Delivery & architecture audit (audit-2)

**Date:** 2026-04-18
**Workspace:** `/home/leul/Downloads/task-43` (application under `repo/`)
**Business target (summary):** On-prem sports retail catalog, perishable inventory, local news ingestion, employee assessments, Flask + SQLite + HTMX; roles include admin, content editor, inventory manager, trainer, staff; JWT sessions, HMAC on mutations, CSRF, rate limits, audit/anomaly logging.

**Audit boundary:** Code and documentation reviewed statically. Runtime behavior outside the regression runs recorded by the test harness is **Cannot Confirm Statistically**.

---

## 1. Verdict

**Partial Pass**

The `repo/` tree is a coherent product-shaped Flask application with documented run paths, tests, and security-oriented middleware. **Pass** on structure, presence of core domains, and several security controls with file/line evidence. **Partial Pass** overall because the open items below still depend on deployment-time verification or test breadth that a static audit cannot close.

---

## 2. Open findings

### 2.1 CSRF coverage breadth

**Conclusion:** Partial Pass.

**Rationale:** `Flask-WTF` CSRF is enabled globally via `csrf.init_app(app)` in `repo/app/__init__.py:69` and toggled by `WTF_CSRF_ENABLED` (default `true`) in `repo/app/config.py:20`. The dedicated `TestCSRFEnforcement` block in `repo/unit_tests/test_security.py:222–284` asserts the enabled-CSRF path on `/auth/sign`. Other CSRF-exposed JSON mutation endpoints are not individually exercised under `WTF_CSRF_ENABLED=True`; they rely on the extension's global wiring to enforce the check.

**Static recommendation:** Add one representative CSRF-enabled test per JSON mutation route family (products, inventory, assessments) so future refactors cannot silently bypass the token check without a failing test.

---

### 2.2 Rate-limiter storage backend under multi-worker deployment

**Conclusion:** Cannot Confirm Statistically.

**Rationale:** `repo/app/config.py:28` defaults `RATELIMIT_STORAGE_URI` to `memory://`. `repo/.env.example:15` includes a commented Redis example. Per-process in-memory storage does not share counters across Gunicorn workers, so the `60 requests/minute/user` ceiling is only enforced per worker when more than one worker is running. Real-world correctness of the limiter under `--workers > 1` requires a Redis (or equivalent shared store) that this audit cannot provision.

**Static recommendation:** For multi-worker production: set `RATELIMIT_STORAGE_URI=redis://…` and add a runtime warning (or startup assertion) when `WORKERS > 1` and the URI still resolves to `memory://`.

---

## 3. Environment, deployment and runtime claims requiring manual verification

- Browser-based visual verification of HTMX partial swaps and Bootstrap layout (no browser session was opened by this audit).
- Behaviour of the APScheduler job registration when Gunicorn runs with more than one worker.
- SQLite concurrency under sustained write pressure on the reservation flow.

These items are **Cannot Confirm Statistically** and are not code defects; they are noted so an operator knows what still needs a runtime pass before release.
