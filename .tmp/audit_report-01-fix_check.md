# Audit Report 01 — Fix Check

**Date:** 2026-04-18
**Scope:** Resolved findings from the audit 01 review of `repo/`, with a brief note on how each was fixed.

---

## High-severity issues

### 1. Trainer assessment/question mutations lack object-level ownership

A `_trainer_owns_assessment` guard was added in `repo/app/assessments/routes.py:28–31` and invoked on every mutate / grade / detail / index route (lines `84–86`, `99–101`, `119–121`, `133–136`, `154–157`, `173–176`, `186–189`, `337–339`, `376–378`). The `/assessments/` listing now filters by `Assessment.created_by` for trainers (`41–46`). Negative regression tests were added in `repo/unit_tests/test_assessments.py` (peer-trainer PUT) and `repo/API_tests/test_api_assessments.py` (`test_trainer_cannot_update_peer_assessment`, `test_trainer_cannot_grade_peer_assignment`). A second trainer now receives `403`/`404` instead of being able to edit a peer's resource.

### 2. Compose default points at demo `env_file`

`repo/docker-compose.yml:12` now reads `env_file: .env`. The README quick-start instructs `cp .env.example .env` as the first step (`repo/README.md:16`, `37`). Docker compose fails fast if `.env` is missing, so the accidental demo-config path is gone.

---

## Medium-severity issues

### 3. Workspace root lacks onboarding README

A root `README.md` now exists at `/home/leul/Downloads/task-43/README.md`. It states the runnable application lives under `repo/`, points at `repo/README.md` for setup, references `metadata.json`, and provides a one-line Docker quick-start.

### 4. Documented test entry requires Docker

`repo/README.md:57–62` documents the non-Docker path: set the four env vars and run `python -m pytest unit_tests/ API_tests/ -v --tb=short`. The Docker variant (`./run_tests.sh`) is kept for CI-parity.

### 5. News ingestion backoff vs prompt (1, 5, 15 minutes)

`repo/app/news/ingest.py:37–44` now maps `{1: 1m, 2: 5m, 3: 15m}` (prompt-aligned 1 / 5 / 15). An inline comment notes the prompt alignment.

### 6. `cryptography` unpinned in requirements

`repo/requirements.txt:13` is now `cryptography==44.0.2`. Every dependency in the file is now pinned.

---

## Low-severity issues

### 7. `test_timestamp_skew_rejected` did not isolate the skew branch

`repo/unit_tests/test_security.py:42` now signs with `user.get_hmac_key()` (decrypted) instead of `user.hmac_key` (ciphertext). The signature matches the server's expected digest, so a `401` now proves the skew branch specifically, not an accidental signature mismatch.

### 8. Duplicate `JWT_VERIFY_SUB` in config

`repo/app/config.py` now contains a single `JWT_VERIFY_SUB = False` (line 18). The duplicate line was removed.

### 9. IDOR saved-search DELETE could return 401 before 403

Tests in `repo/unit_tests/test_security.py` now call the DELETE path with full signed HMAC headers (via `hmac_headers`) so the request reaches the ownership check. The assertion distinguishes `403` (ownership) from `401` (auth).

---

## Configuration / documentation fixes

### 10. JWT cookie config knobs were implicit

`repo/app/config.py:22–25` now exposes `JWT_COOKIE_CSRF_PROTECT`, `JWT_COOKIE_SECURE`, and `JWT_COOKIE_SAMESITE` as environment-driven options with safe defaults (CSRF on, `SameSite=Lax`). `repo/README.md:74` documents flipping `JWT_COOKIE_SECURE=true` behind HTTPS. Production wiring is explicit rather than implicit.

### 11. Scheduler behaviour under multi-worker Gunicorn was undocumented

`repo/README.md:89` adds a Known Limitations entry: run Gunicorn with `--workers 1` or move scheduling to cron. Operators now have an authoritative note instead of discovering duplicated jobs at runtime.
