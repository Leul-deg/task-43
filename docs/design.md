# Sports Hub Design

## Architecture Overview
Sports Hub is a Flask 3.x application with a SQLite backing store and HTMX-driven UI. The server exposes role-protected routes for catalog, inventory, pricing, news ingestion, search, and assessments. Background jobs run via APScheduler for reservation cleanup and nonce cleanup.

## Module List
- app/__init__.py: App factory, extension setup, CLI commands, and scheduler wiring.
- app/config.py: Environment-driven configuration defaults.
- app/extensions.py: SQLAlchemy, JWT, CSRF, and rate limiting instances.
- app/models.py: All SQLAlchemy models and relationships.
- app/auth/: Login, logout, refresh, and lockout logic.
- app/products/: Catalog management, tagging, variants, import/export, and HTMX pages.
- app/inventory/: Warehouses, bins, batches, stock counts, reservations, FEFO picking.
- app/pricing/: Pricing rules and effective price calculation.
- app/search/: Unified search with saved searches and anomalies.
- app/news/: News sources, ingestion, quarantine, and content management.
- app/assessments/: Assessment authoring, assignment, taking, and grading.
- app/admin/: Admin dashboards for anomalies, audit log, and user management.
- app/static/: Styles, HMAC signing script, and uploads.
- templates/: Bootstrap + HTMX templates.

## Data Model Summary
- User: username, password_hash, hmac_key, role, lockout fields, created_at.
- AuditLog: user_id, action, detail, ip_address, created_at.
- UsedNonce: nonce, created_at.
- AnomalyAlert: user_id, rule_triggered, detail, severity, review fields.
- Product: name, slug, description, primary_image, is_published, purchase_limit.
- Tag: name; many-to-many via product_tags.
- Category: name, description.
- ProductVariant: product_id, sku, category_id, base_price.
- TieredPrice: variant_id, min_quantity, unit_price.
- Warehouse: name, location.
- Bin: warehouse_id, label.
- Batch: variant_id, bin_id, quantity, expiration_date, received_at.
- StockCount: batch_id, expected_qty, counted_qty, variance fields, counted_by.
- Reservation: variant_id, user_id, quantity, held_at, expires_at, status.
- PriceRule: variant_id, rule_type, value, start/end dates, booking windows.
- NewsSource: name, source_type, parsing_rules, is_allowed, created_by.
- NewsItem: source_id, title, summary, content, author, published_date, file_hash.
- IngestionLog: source_id, filename, status, message, retries, timestamps.
- QuarantinedFile: filename, reason, file_hash, quarantined_at.
- SavedSearch: user_id, name, query_params, is_pinned, created_at.
- Assessment: title, description, created_by, is_published, limits, passing_score.
- Question: assessment_id, question_text, question_type, options, correct_answer.
- AssessmentAssignment: assessment_id, user_id, assigned_by, status, dates.
- UserAnswer: assignment_id, question_id, answer_text, is_correct, points_earned.
- AssessmentResult: assignment_id, total/max score, percentage, passed, graded_by.

## Security Design
- JWT auth in cookies for session management.
- HMAC-SHA256 signing for data-modifying requests with nonce + timestamp.
- Account lockout after repeated login failures.
- Rate limiting via Flask-Limiter defaults.
- Role-based access control (RBAC) per route.
- Bleach sanitization for rich text fields.
- Anomaly detection for failed logins, search bursts, and hold activity.

## Deployment
- Dockerfile builds a slim Python image and runs gunicorn.
- docker-compose.yml mounts data and upload volumes and loads .env.
- SQLite WAL enabled for concurrent reads/writes.
