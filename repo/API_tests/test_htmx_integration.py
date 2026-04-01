"""Integration tests for HTMX partial-response flows.

HTMX behaviour is deterministic: the server returns an HTML fragment and
HTMX swaps it into the DOM.  These tests verify the server returns the
correct partial (not the full page) when the ``HX-Request: true`` header
is present, and that the partials contain expected content.
"""
from app.extensions import db
from app.models import (
    Batch, Bin, Product, ProductVariant, User, Warehouse,
    NewsItem, NewsSource,
)
from conftest import hmac_headers, login_as


def _seed_product(app):
    with app.app_context():
        product = Product(name="HTMX Ball", slug="htmx-ball", is_published=True)
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id, sku="HX-001", base_price=29.99
        )
        db.session.add(variant)
        warehouse = Warehouse(name="HW")
        db.session.add(warehouse)
        db.session.flush()
        bin_item = Bin(warehouse_id=warehouse.id, label="HB1")
        db.session.add(bin_item)
        db.session.flush()
        db.session.add(
            Batch(variant_id=variant.id, bin_id=bin_item.id, quantity=20)
        )
        db.session.commit()
        return product, variant


def test_search_htmx_returns_partial(app, client):
    """GET /search with HX-Request returns only the results partial,
    not the full page with <html> and filter controls."""
    _seed_product(app)
    login_as(client, "staff")

    resp = client.get("/search/?q=HTMX", headers={"HX-Request": "true"})
    html = resp.data.decode()

    assert resp.status_code == 200
    assert "<html" not in html
    assert "HTMX Ball" in html


def test_search_full_page_without_htmx(app, client):
    """GET /search without HX-Request returns the full page layout."""
    _seed_product(app)
    login_as(client, "staff")

    resp = client.get("/search/?q=HTMX")
    html = resp.data.decode()

    assert resp.status_code == 200
    assert "<html" in html or "<!doctype" in html.lower() or "<!DOCTYPE" in html
    assert "HTMX Ball" in html


def test_search_filter_by_type_htmx(app, client):
    """Filtering by type=products via HTMX returns only product results."""
    _seed_product(app)
    with app.app_context():
        src = NewsSource(name="HX", source_type="rss", is_allowed=True, created_by=1)
        db.session.add(src)
        db.session.flush()
        db.session.add(
            NewsItem(title="HTMX News", summary="s", source_id=src.id,
                     file_hash="testhash123")
        )
        db.session.commit()

    login_as(client, "staff")

    resp = client.get(
        "/search/?q=HTMX&type=products", headers={"HX-Request": "true"}
    )
    html = resp.data.decode()
    assert "HTMX Ball" in html
    assert "HTMX News" not in html

    resp2 = client.get(
        "/search/?q=HTMX&type=news", headers={"HX-Request": "true"}
    )
    html2 = resp2.data.decode()
    assert "HTMX News" in html2
    assert "HTMX Ball" not in html2


def test_products_htmx_returns_table_rows(app, client):
    """GET /products with HX-Request returns table rows partial, not full page."""
    _seed_product(app)
    login_as(client, "admin")

    resp = client.get("/products/?q=HTMX", headers={"HX-Request": "true"})
    html = resp.data.decode()

    assert resp.status_code == 200
    assert "<html" not in html
    assert "HX-001" in html


def test_product_publish_toggle_returns_partial(app, client):
    """POST toggle-publish returns a publish-button partial, not a redirect."""
    product, variant = _seed_product(app)
    login_as(client, "admin")

    with app.app_context():
        user = User.query.filter_by(username="test_admin").first()
        data = {}
        headers = hmac_headers(
            user, "POST",
            f"/products/{product.id}/toggle-publish", data,
        )

    resp = client.post(
        f"/products/{product.id}/toggle-publish",
        data=data, headers=headers,
    )

    assert resp.status_code == 200
    html = resp.data.decode()
    assert "<html" not in html
    assert "Published" in html or "Hidden" in html


def test_search_pagination_htmx(app, client):
    """Paginated HTMX search requests return partial results."""
    with app.app_context():
        for i in range(30):
            p = Product(name=f"PaginatedItem{i}", slug=f"pi-{i}", is_published=True)
            db.session.add(p)
            db.session.flush()
            db.session.add(
                ProductVariant(product_id=p.id, sku=f"PI-{i:03d}", base_price=5.0)
            )
        db.session.commit()

    login_as(client, "staff")

    resp_p1 = client.get(
        "/search/?q=PaginatedItem&type=products&page=1",
        headers={"HX-Request": "true"},
    )
    resp_p2 = client.get(
        "/search/?q=PaginatedItem&type=products&page=2",
        headers={"HX-Request": "true"},
    )

    assert resp_p1.status_code == 200
    assert resp_p2.status_code == 200
    assert "<html" not in resp_p1.data.decode()
    assert "<html" not in resp_p2.data.decode()
    assert "PaginatedItem" in resp_p1.data.decode()
