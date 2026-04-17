"""
HTMX partial-render tests.

Routes that branch on `HX-Request: true` must return a partial HTML fragment
(no <html> wrapper) when the header is set, and a full HTML page otherwise.
"""
from app.extensions import db
from app.models import Product, ProductVariant
from conftest import login_as


def _make_product(app, name, sku):
    with app.app_context():
        p = Product(name=name, slug=sku.lower(), is_published=True)
        db.session.add(p)
        db.session.flush()
        db.session.add(ProductVariant(product_id=p.id, sku=sku, base_price=10.0))
        db.session.commit()


def test_products_list_full_page_without_htmx_header(client, app):
    _make_product(app, "HTMX Product", "HTMX-1")
    login_as(client, "staff")
    resp = client.get("/products/")
    assert resp.status_code == 200
    assert b"<html" in resp.data or b"<!DOCTYPE" in resp.data


def test_products_list_htmx_returns_partial(client, app):
    """With HX-Request: true the product list route returns a partial fragment, not a full page."""
    _make_product(app, "Partial Product", "PART-1")
    login_as(client, "staff")
    resp = client.get("/products/", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "<html" not in html
    assert "<!DOCTYPE" not in html


def test_search_full_page_without_htmx_header(client, app):
    login_as(client, "staff")
    resp = client.get("/search/?q=test")
    assert resp.status_code == 200
    assert b"<html" in resp.data or b"<!DOCTYPE" in resp.data


def test_search_htmx_returns_partial(client, app):
    """With HX-Request: true the search route returns a results partial, not a full page."""
    login_as(client, "staff")
    resp = client.get("/search/?q=test", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "<html" not in html
    assert "<!DOCTYPE" not in html
