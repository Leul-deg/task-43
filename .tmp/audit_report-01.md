# Delivery Acceptance & Project Architecture — Static Audit Report

**Date:** 2026-04-17
**Workspace:** `/home/leul/Downloads/task-43`
**Primary implementation path:** `repo/` (Flask application, SQLite, HTMX templates)
**Audit type:** Static analysis only (no project start, Docker, tests executed, or code changes)

---

## 1. Verdict

**Overall conclusion: Partial Pass**

The `repo/` tree contains a structured Flask application with models and routes that map substantively to the Sports Venue Commerce & Knowledge Hub prompt (catalog, inventory, news ingestion, assessments, unified search, JWT + HMAC, CSRF hooks, rate limiting hooks, audit/anomaly tables). Static evidence supports a serious implementation rather than a fragment.

Gaps that prevent a full Pass are captured below. They are either **static-only limitations** (runtime behavior, visual QA, full JWT cookie hardening under TLS that cannot be proven without execution) or **product/interpretation deviations from the prompt text** (role breadth on inventory reads, allow/block-list modeling) that remain even after refactors.

---

## 2. Scope and Static Verification Boundary

**Reviewed (representative, not every line):**

- Workspace layout: `metadata.json`, `docs/`, `repo/`
- `repo/README.md`, `repo/requirements.txt`, `repo/.env.example`, `repo/docker-compose.yml`, `repo/Dockerfile`
- Application factory and wiring: `repo/app/__init__.py`, `repo/app/config.py`, `repo/app/extensions.py`
- Security-critical: `repo/app/auth/routes.py`, `repo/app/decorators.py`, `repo/app/models.py`
- Core domains: `repo/app/search/routes.py`, `repo/app/inventory/routes.py`, `repo/app/products/routes.py` (partial), `repo/app/news/ingest.py`, `repo/app/news/routes.py`, `repo/app/pricing/services.py`, `repo/app/pricing/routes.py`, `repo/app/assessments/routes.py`, `repo/app/dashboard/routes.py`

**Intentionally not executed (per audit rules):** Application server, Gunicorn, pytest, Docker builds/containers.

**Claims requiring manual verification:** Any statement that flows "work in the browser" without errors, exact CSRF + JWT cookie interaction in production browsers, scheduler behavior under multi-worker Gunicorn, SQLite contention under load, and visual design quality.

---

## 3. Open findings

### 3.1 Broader role access to inventory views and reservations than the prompt wording

**Conclusion:** Partial Pass (prompt deviation, accepted product choice but still visible to any reader comparing to the spec).

**Rationale:** `content_editor` and `trainer` share read access to several inventory/reservation routes alongside staff (`repo/app/inventory/routes.py:30–31`, `117–120`, `258–260`, `271–273`). The prompt emphasises the **Inventory Manager** as the stock-controlling role. Mutating routes are correctly gated, but the read surface is wider than the spec text suggests.

**Evidence:** `repo/app/inventory/routes.py:30–31`, `117–120`, `258–273`.

**Static recommendation:** Either narrow the `role_required(...)` list on those reads or document the intent directly in the source (docstring / README table) so reviewers do not re-raise the same observation.

---

### 3.2 News "allow/block lists" modeled as a single boolean

**Conclusion:** Partial Pass (functional but not a literal match to the prompt).

**Rationale:** The prompt describes **admin-managed allow / block lists**. The implementation uses a single `NewsSource.is_allowed` flag plus `/news/sources` CRUD (`repo/app/models.py:228–235`, `repo/app/news/ingest.py:154–157`). Setting `is_allowed=False` blocks a source at ingest. There is no separate "block list" artifact; the same table supports both semantics via the boolean.

**Evidence:** `repo/app/models.py:228–235`; `repo/app/news/ingest.py:154–157`.

**Static recommendation:** Either introduce a distinct `NewsBlockList` (if auditors expect a 1:1 literal match) or add a short note in `repo/README.md` / source docstring explaining the single-flag design.

---

### 3.3 Silent redirect on bad dates in admin form paths

**Conclusion:** Partial Pass (UX for HTMX form users is fine; a strict API-consumer perspective sees weaker error signalling).

**Rationale:** Admin form handlers return a redirect + flash message on invalid date input rather than a 400 body (`repo/app/pricing/routes.py:36–40` and neighbouring admin CRUD flows). API consumers that submit JSON-like payloads to these endpoints will see a 302 and a flash rendered in the next page rather than a machine-readable error.

**Evidence:** `repo/app/pricing/routes.py:36–40`.

**Static recommendation:** When `request.accept_mimetypes.best` resolves to `application/json`, return a 400 JSON payload instead of the redirect.

---

### 3.4 Usernames appear in authentication warning logs

**Conclusion:** Partial Pass — low sensitivity, but not "masked" in the sense some reviewers expect.

**Rationale:** Auth warnings emit the username (and hashed IP) on failed logins and lockouts (`repo/app/auth/routes.py:89`). Passwords, tokens, and HMAC keys are not logged. Whether usernames count as PII depends on the deployment context.

**Evidence:** `repo/app/auth/routes.py:89`.

**Static recommendation:** If the deployment treats usernames as PII, replace them with `user.id` or a per-session correlation ID in warning logs.

---

### 3.5 Aesthetics / HTMX UX cannot be confirmed statically

**Conclusion:** Cannot Confirm Statistically.

**Rationale:** Static files show Bootstrap + HTMX (`repo/app/templates/base.html`), `repo/app/static/css/style.css`, and vendor bundles. No browser rendering was performed, so hover/spacing/contrast, HTMX partial-swap smoothness, and empty/error states cannot be validated statically beyond noting that the structure exists.

**Evidence:** `repo/app/templates/base.html`; `repo/app/static/css/style.css`.

**Static recommendation:** A browser pass against the flows listed in `repo/README.md` (login, search, reservation, assessment submit) would close this item.

---

### 3.6 Production JWT cookie hardening behind TLS

**Conclusion:** Cannot Confirm Statistically (runtime / deployment dependent).

**Rationale:** `repo/app/config.py` exposes `JWT_COOKIE_CSRF_PROTECT`, `JWT_COOKIE_SECURE`, and `JWT_COOKIE_SAMESITE` as env-driven options with safe defaults. However, `JWT_COOKIE_SECURE` defaults to `false` (to keep local `http://` demos working) and there is no automatic enforcement tied to `FLASK_ENV=production`. Whether a production deployment flips it on — and whether the HTTPS terminator is actually present — cannot be proven from the repository alone.

**Evidence:** `repo/app/config.py:22–25`.

**Static recommendation:** Add a runtime assertion that `JWT_COOKIE_SECURE` must be `true` when `DEMO_MODE` is unset, or document a deploy checklist alongside the HTTPS reverse-proxy setup.

---

## 4. Security Review (static, open items only)

| Area | Conclusion | Evidence |
|------|------------|----------|
| **Object-level authorization — inventory read scope** | Partial Pass (see 3.1) | `repo/app/inventory/routes.py:30–31`, `117–120`, `258–273` |
| **JWT cookie hardening for production TLS** | Cannot Confirm Statistically (see 3.6) | `repo/app/config.py:22–25` |
| **Sensitive-data posture in logs** | Partial Pass (see 3.4) | `repo/app/auth/routes.py:89` |

**Cannot Confirm Statistically:** Production-hardening of JWT cookies under TLS; scheduler behaviour under multi-worker Gunicorn (documented in `repo/README.md` Known Limitations but not enforced).

---

## 5. Final Notes

This audit is **evidence-bound to file paths under the workspace**; runtime correctness, test pass/fail counts, and UI appearance are out of scope. The remaining findings are all either **static-only limitations** (§3.5, §3.6) or **prompt-literal-vs-functional deviations** (§3.1, §3.2) that are safe to accept as product decisions once documented.
