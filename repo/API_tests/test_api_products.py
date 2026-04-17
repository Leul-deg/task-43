import io

from app.extensions import db
from app.models import Category, Product, ProductVariant, Tag, TieredPrice, User
from conftest import hmac_headers, login_as


def test_get_list_paginated(client, app):
    with app.app_context():
        for i in range(5):
            product = Product(name=f"API Product {i}", slug=f"api-product-{i}")
            db.session.add(product)
            db.session.flush()
            db.session.add(ProductVariant(product_id=product.id, sku=f"API-{i}", base_price=5))
        db.session.commit()

    login_as(client, "staff")
    response = client.get("/products/?page=1")
    assert response.status_code == 200


def test_post_create_admin_ok_staff_forbidden(client, app):
    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()
    data = {"name": "Admin Product", "slug": "admin-product", "sku": "ADMIN-1", "base_price": "10"}
    headers = hmac_headers(admin, "POST", "/products/", data)
    response = client.post("/products/", data=data, headers=headers)
    assert response.status_code == 302

    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
    headers = hmac_headers(staff, "POST", "/products/", data)
    response = client.post("/products/", data=data, headers=headers)
    assert response.status_code == 403


def test_csv_import_export(client, app):
    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()
    content = "name,sku,description,category,tags,base_price,stock_total,purchase_limit\n"
    content += "API Import,API-IMP,Desc,Category,tag1,12.5,0,\n"
    content_bytes = content.encode("utf-8")
    data = {"file": (io.BytesIO(content.encode("utf-8")), "products.csv")}
    headers = hmac_headers(
        admin,
        "POST",
        "/products/import",
        file_meta=[("file", "products.csv", content_bytes)],
    )
    response = client.post("/products/import", data=data, headers=headers)
    assert response.status_code == 302

    response = client.get("/products/export")
    assert response.status_code == 200


def _make_product(app, name, sku, price=10.0, category_id=None):
    with app.app_context():
        product = Product(name=name, slug=sku.lower())
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id, sku=sku, base_price=price, category_id=category_id
        )
        db.session.add(variant)
        db.session.commit()
        return product.id, variant.id


def test_get_product_detail(client, app):
    product_id, _ = _make_product(app, "Detail Product", "DET-1", price=25.0)
    login_as(client, "staff")
    response = client.get(f"/products/{product_id}")
    assert response.status_code == 200


def test_toggle_publish_admin_ok(client, app):
    product_id, _ = _make_product(app, "Toggle Product", "TOG-1")
    with app.app_context():
        Product.query.get(product_id).is_published = False
        db.session.commit()

    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    headers = hmac_headers(admin, "POST", f"/products/{product_id}/toggle-publish")
    resp = client.post(f"/products/{product_id}/toggle-publish", headers=headers)
    assert resp.status_code == 200

    with app.app_context():
        assert Product.query.get(product_id).is_published is True


def test_toggle_publish_staff_forbidden(client, app):
    product_id, _ = _make_product(app, "Guard Toggle", "GTO-1")

    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()

    headers = hmac_headers(staff, "POST", f"/products/{product_id}/toggle-publish")
    resp = client.post(f"/products/{product_id}/toggle-publish", headers=headers)
    assert resp.status_code == 403


def test_delete_product_unpublishes(client, app):
    product_id, _ = _make_product(app, "Deletable Product", "DEL-1")

    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    headers = hmac_headers(admin, "DELETE", f"/products/{product_id}")
    resp = client.delete(f"/products/{product_id}", headers=headers)
    assert resp.status_code == 204

    with app.app_context():
        assert Product.query.get(product_id).is_published is False


def test_add_variant_ok_and_duplicate_sku_rejected(client, app):
    product_id, _ = _make_product(app, "Variant Product", "VAR-BASE")

    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    data = {"sku": "VAR-NEW", "base_price": "20.0"}
    headers = hmac_headers(admin, "POST", f"/products/{product_id}/variants", data)
    resp = client.post(f"/products/{product_id}/variants", data=data, headers=headers)
    assert resp.status_code == 200

    with app.app_context():
        v = ProductVariant.query.filter_by(sku="VAR-NEW").first()
        assert v is not None
        assert v.base_price == 20.0

    headers = hmac_headers(admin, "POST", f"/products/{product_id}/variants", data)
    resp = client.post(f"/products/{product_id}/variants", data=data, headers=headers)
    assert resp.status_code == 409


def test_update_variant(client, app):
    _, variant_id = _make_product(app, "Updatable Variant", "UPV-1", price=10.0)

    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    data = {"sku": "UPV-1", "base_price": "99.0"}
    headers = hmac_headers(admin, "PUT", f"/products/variants/{variant_id}", data)
    resp = client.put(f"/products/variants/{variant_id}", data=data, headers=headers)
    assert resp.status_code == 200

    with app.app_context():
        assert ProductVariant.query.get(variant_id).base_price == 99.0


def test_create_product_with_tiered_pricing(client, app):
    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    data = {
        "name": "Tiered Product",
        "sku": "TIER-API-1",
        "base_price": "100.0",
        "tiered_min[]": ["5", "10"],
        "tiered_price[]": ["90.0", "80.0"],
    }
    headers = hmac_headers(admin, "POST", "/products/", data)
    resp = client.post("/products/", data=data, headers=headers, follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        variant = ProductVariant.query.filter_by(sku="TIER-API-1").first()
        assert variant is not None
        tiers = (
            TieredPrice.query.filter_by(variant_id=variant.id)
            .order_by(TieredPrice.min_quantity)
            .all()
        )
        assert len(tiers) == 2
        assert tiers[0].min_quantity == 5 and tiers[0].unit_price == 90.0
        assert tiers[1].min_quantity == 10 and tiers[1].unit_price == 80.0


def test_product_list_sort_by_name(client, app):
    _make_product(app, "Zzz Last Product", "SORT-Z")
    _make_product(app, "Aaa First Product", "SORT-A")

    login_as(client, "staff")
    resp = client.get("/products/?sort=name")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert html.index("Aaa First Product") < html.index("Zzz Last Product")


def test_product_list_compound_filter_price_and_category(client, app):
    with app.app_context():
        cat = Category(name="CompoundCat")
        db.session.add(cat)
        db.session.commit()
        cat_id = cat.id

    _make_product(app, "Compound Match", "CMATCH-1", price=200.0, category_id=cat_id)
    _make_product(app, "Wrong Category Item", "WCAT-1", price=200.0, category_id=None)
    _make_product(app, "Wrong Price Item", "WPRICE-1", price=5.0, category_id=cat_id)

    login_as(client, "staff")
    resp = client.get(f"/products/?min_price=100&category_id={cat_id}")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "Compound Match" in html
    assert "Wrong Category Item" not in html
    assert "Wrong Price Item" not in html


def test_update_product_admin_ok(client, app):
    product_id, _ = _make_product(app, "Original Name", "UPD-1", price=10.0)

    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    data = {
        "name": "Updated Name",
        "slug": "updated-name",
        "description": "New description",
        "tags": "sale, clearance",
        "purchase_limit": "5",
    }
    headers = hmac_headers(admin, "PUT", f"/products/{product_id}", data)
    resp = client.put(f"/products/{product_id}", data=data, headers=headers)
    assert resp.status_code == 200

    with app.app_context():
        product = Product.query.get(product_id)
        assert product.name == "Updated Name"
        assert product.purchase_limit == 5
        tag_names = {t.name for t in product.tags}
        assert "sale" in tag_names
        assert "clearance" in tag_names


def test_update_product_staff_forbidden(client, app):
    product_id, _ = _make_product(app, "Guard Update Product", "GUPD-1")

    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()

    data = {"name": "Hijacked", "slug": "hijacked", "description": "", "tags": ""}
    headers = hmac_headers(staff, "PUT", f"/products/{product_id}", data)
    resp = client.put(f"/products/{product_id}", data=data, headers=headers)
    assert resp.status_code == 403
