# Audit Report 02 — Fix Check

**Date:** 2026-04-17
**Scope:** Resolved findings from the audit 02 review of `repo/`, with a brief note on how each was fixed.

---

### 1. Full test matrix had not been executed end-to-end

The full suite was run against a rebuilt Docker image via `./run_tests.sh`. Result: **194 passed, 0 failed, 1081 warnings in 143.62s**. The command covers both `unit_tests/` and `API_tests/` (including the e2e workflows). Specific repairs needed to reach the green run:

- `repo/app/decorators.py` HMAC body canonicalisation now sorts combined items by `(key, str(value))` so multi-value form fields (e.g. `tiered_min[]`) match the signing helper in `conftest.py`.
- `repo/app/decorators.py` guarded `stream.tell()` / `stream.seek()` on multipart uploads (Python 3.10's `SpooledTemporaryFile` lacked `seekable`).
- `repo/app/search/routes.py::toggle_pin` now passes `params` into `search/partials/saved_button.html`; the template also tolerates a missing `params`.
- `repo/API_tests/test_api_admin.py` received the missing `datetime` import and the anomaly-filter assertion was rewritten to use unique sentinel strings instead of relying on the `"Unreviewed"` substring overlap.
- `repo/API_tests/test_api_auth.py` and `repo/API_tests/test_e2e_workflows.py` replaced the removed Werkzeug `client.cookie_jar` API with `client.get_cookie(...)`.
- `repo/API_tests/test_e2e_workflows.py::test_staff_login_search_reserve_flow` also accepts `201 CREATED` as a valid reservation response.
- `repo/Dockerfile`'s `pip install` now uses `--default-timeout=180 --retries 5` so the image builds reliably on slower mirrors.

### 2. Rate-limiter storage configuration was implicit

`repo/app/config.py:28` now sets `RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")`, which removes the Flask-Limiter "no storage specified" startup warning. `repo/.env.example:15` exposes a commented Redis example (`RATELIMIT_STORAGE_URI=redis://localhost:6379/0`) and `repo/README.md:75` plus the Known Limitations section instruct operators to set a Redis URI for multi-worker deployments. The configuration layer is explicit and documented.
