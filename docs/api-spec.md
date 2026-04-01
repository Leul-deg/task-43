# Sports Hub API Spec

## Auth
- POST `/auth/login` (public): form params `username`, `password`. 302 on success, 401 on failure, 423 on locked.
- GET `/auth/login` (public): login form.
- POST `/auth/logout` (auth): clears cookies, 302 redirect.
- POST `/auth/refresh` (auth): refresh access token.

## Dashboard
- GET `/` (auth): dashboard view with summary metrics.

## Products
- GET `/products/` (auth): params `q`, `category_id`, `tag_id`, `min_price`, `max_price`, `sort`, `page`, `per_page`.
- GET `/products/new` (admin, content_editor): create form.
- POST `/products/` (admin, content_editor, HMAC): create product + first variant.
- GET `/products/<id>` (auth): product detail.
- GET `/products/<id>/edit` (admin, content_editor).
- PUT `/products/<id>` (admin, content_editor, HMAC): update product.
- DELETE `/products/<id>` (admin, content_editor, HMAC): soft delete.
- POST `/products/<id>/toggle-publish` (admin, content_editor, HMAC).
- POST `/products/<id>/variants` (admin, content_editor, HMAC).
- PUT `/products/variants/<id>` (admin, content_editor, HMAC).
- GET `/products/export` (admin, content_editor): CSV download.
- POST `/products/import` (admin, content_editor, HMAC): CSV upload.

## Inventory
- GET `/inventory/` (auth): dashboard.
- GET `/inventory/warehouses` (admin, inventory_manager).
- POST `/inventory/warehouses` (admin, inventory_manager).
- POST `/inventory/warehouses/<id>/bins` (admin, inventory_manager).
- GET `/inventory/batches` (auth): filters `warehouse_id`, `variant_id`, `expiring_within`.
- POST `/inventory/batches` (inventory_manager).
- GET `/inventory/batches/<id>/pick` (auth): FEFO pick list.
- GET `/inventory/stock-count` (inventory_manager).
- POST `/inventory/stock-count` (inventory_manager): variance validation.
- GET `/inventory/reservations` (auth): list reservations.
- POST `/inventory/reservations` (auth, HMAC): create hold.
- POST `/inventory/reservations/<id>/confirm` (admin, inventory_manager, HMAC).
- POST `/inventory/reservations/<id>/release` (auth, HMAC).

## Pricing
- GET `/pricing/rules` (admin).
- POST `/pricing/rules` (admin, HMAC).
- PUT `/pricing/rules/<id>` (admin, HMAC).
- DELETE `/pricing/rules/<id>` (admin, HMAC).
- GET `/pricing/calculate` (auth): query `variant_id`, `quantity`.

## Search
- GET `/search/` (auth): params `q`, `type`, `category_id`, `tag_id`, `min_price`, `max_price`, `date_from`, `date_to`, `sort`, `page`.
- POST `/search/saved` (auth, HMAC): save search.
- GET `/search/saved` (auth): list saved.
- DELETE `/search/saved/<id>` (auth, HMAC): delete saved.
- POST `/search/saved/<id>/pin` (auth, HMAC): toggle pin.

## News
- GET `/news/` (auth): filters `source_id`, `date_from`, `date_to`.
- GET `/news/<id>` (auth): detail.
- GET `/news/sources` (admin).
- POST `/news/sources` (admin).
- PUT `/news/sources/<id>` (admin).
- DELETE `/news/sources/<id>` (admin).
- PUT `/news/<id>` (content_editor): edit content.
- GET `/news/logs` (admin).
- GET `/news/quarantine` (admin).
- POST `/news/quarantine/<id>/release` (admin).
- DELETE `/news/quarantine/<id>` (admin).

## Assessments
- GET `/assessments/` (trainer, staff, admin).
- POST `/assessments/` (trainer, HMAC).
- GET `/assessments/<id>` (trainer, staff, admin).
- PUT `/assessments/<id>` (trainer, HMAC).
- POST `/assessments/<id>/toggle-publish` (trainer, HMAC).
- POST `/assessments/<id>/questions` (trainer, HMAC).
- PUT `/assessments/questions/<id>` (trainer, HMAC).
- DELETE `/assessments/questions/<id>` (trainer, HMAC).
- POST `/assessments/<id>/assign` (trainer, HMAC).
- GET `/assessments/assignments` (staff).
- POST `/assessments/assignments/<id>/start` (staff, HMAC).
- GET `/assessments/assignments/<id>/take` (staff).
- POST `/assessments/assignments/<id>/submit` (staff, HMAC).
- GET `/assessments/assignments/<id>/results` (staff, trainer, admin).
- POST `/assessments/assignments/<id>/grade` (trainer, HMAC).

## Admin
- GET `/admin/` (admin): dashboard.
- GET `/admin/anomalies` (admin): filters `reviewed`, `sort`.
- POST `/admin/anomalies/<id>/review` (admin).
- GET `/admin/audit-log` (auth): filters `action`, `date_from`, `date_to`.
- GET `/admin/users` (admin).
- POST `/admin/users` (admin).
- POST `/admin/users/<id>/lock` (admin).
- POST `/admin/users/<id>/unlock` (admin).

## Example Curl (HMAC)
```bash
curl -X POST http://localhost:5000/search/saved \
  -H "Authorization: Bearer <token>" \
  -H "X-Signature: <sig>" \
  -H "X-Timestamp: 2026-03-27T12:00:00Z" \
  -H "X-Nonce: <uuid>" \
  -d "name=MySearch"
```
