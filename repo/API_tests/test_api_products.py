import io

from app.extensions import db
from app.models import Product, ProductVariant, User
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
    data = {"file": (io.BytesIO(content.encode("utf-8")), "products.csv")}
    headers = hmac_headers(admin, "POST", "/products/import")
    response = client.post("/products/import", data=data, headers=headers)
    assert response.status_code == 302

    response = client.get("/products/export")
    assert response.status_code == 200
