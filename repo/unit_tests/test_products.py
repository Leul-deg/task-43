import io

from app.extensions import db
from app.models import Category, Product, ProductVariant, TieredPrice, User
from app.pricing.services import calculate_effective_price
from conftest import hmac_headers, login_as


def test_create_product(client, app):
    login_as(client, "admin")
    with app.app_context():
        user = User.query.filter_by(username="test_admin").first()
    data = {
        "name": "Runner Ball",
        "slug": "runner-ball",
        "description": "<p>High bounce</p>",
        "sku": "RB-1",
        "base_price": "79",
        "tiered_min[]": ["10"],
        "tiered_price[]": ["69"],
    }
    headers = hmac_headers(user, "POST", "/products/", data)
    response = client.post("/products/", data=data, headers=headers)
    assert response.status_code == 302


def test_list_pagination(client, app):
    with app.app_context():
        for i in range(30):
            product = Product(name=f"Product {i}", slug=f"product-{i}")
            db.session.add(product)
            db.session.flush()
            variant = ProductVariant(product_id=product.id, sku=f"SKU-{i}", base_price=10)
            db.session.add(variant)
        db.session.commit()

    login_as(client, "staff")
    response = client.get("/products/?page=2")
    assert response.status_code == 200
    assert b"Products" in response.data


def test_tiered_pricing(app):
    with app.app_context():
        product = Product(name="Tiered", slug="tiered")
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(product_id=product.id, sku="T-1", base_price=79)
        db.session.add(variant)
        db.session.flush()
        db.session.add(TieredPrice(variant_id=variant.id, min_quantity=10, unit_price=69))
        db.session.commit()

        unit_price, total, _ = calculate_effective_price(variant.id, 1)
        assert unit_price == 79
        unit_price, total, _ = calculate_effective_price(variant.id, 10)
        assert unit_price == 69


def test_publish_toggle(client, app):
    with app.app_context():
        product = Product(name="Toggle", slug="toggle", is_published=True)
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(product_id=product.id, sku="TGL", base_price=10)
        db.session.add(variant)
        db.session.commit()
        user = User.query.filter_by(username="test_admin").first()

    login_as(client, "admin")
    headers = hmac_headers(user, "POST", f"/products/{product.id}/toggle-publish")
    response = client.post(f"/products/{product.id}/toggle-publish", headers=headers)
    assert response.status_code == 200
    with app.app_context():
        updated = Product.query.get(product.id)
        assert updated.is_published is False


def test_csv_import_export(client, app):
    login_as(client, "admin")
    with app.app_context():
        user = User.query.filter_by(username="test_admin").first()

    content = "name,sku,description,category,tags,base_price,stock_total,purchase_limit\n"
    content += "Imported,IMP-1,Desc,Category A,tag1,12.5,0,\n"
    data = {"file": (io.BytesIO(content.encode("utf-8")), "products.csv")}
    headers = hmac_headers(user, "POST", "/products/import")
    response = client.post("/products/import", data=data, headers=headers)
    assert response.status_code == 302

    export = client.get("/products/export")
    assert export.status_code == 200
    assert b"name,sku,description,category,tags,base_price,stock_total,purchase_limit" in export.data
