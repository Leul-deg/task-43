from app.extensions import db
from app.models import Product, ProductVariant, SavedSearch, User
from conftest import hmac_headers, login_as


def test_get_search_and_save_delete(client, app):
    with app.app_context():
        product = Product(name="Searchable", slug="searchable", is_published=True)
        db.session.add(product)
        db.session.flush()
        db.session.add(ProductVariant(product_id=product.id, sku="SEA-1", base_price=10))
        db.session.commit()

    login_as(client, "staff")
    response = client.get("/search/?q=Searchable")
    assert response.status_code == 200

    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
    headers = hmac_headers(staff, "POST", "/search/saved", {"name": "My Search"})
    response = client.post("/search/saved", data={"name": "My Search"}, headers=headers)
    assert response.status_code == 200

    with app.app_context():
        saved = SavedSearch.query.filter_by(user_id=staff.id).first()
    headers = hmac_headers(staff, "DELETE", f"/search/saved/{saved.id}")
    response = client.delete(f"/search/saved/{saved.id}", headers=headers)
    assert response.status_code == 204
