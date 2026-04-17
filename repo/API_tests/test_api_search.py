from datetime import date, timedelta

from app.extensions import db
from app.models import (
    Category, NewsItem, NewsSource, Product, ProductVariant, SavedSearch, Tag, User,
)
from conftest import hmac_headers, login_as


def _seed_product(app, name="Searchable", sku="SEA-1", price=10.0, tag=None, category=None):
    with app.app_context():
        product = Product(name=name, slug=name.lower().replace(" ", "-"), is_published=True)
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id, sku=sku, base_price=price,
            category_id=category.id if category else None,
        )
        db.session.add(variant)
        if tag:
            product.tags.append(tag)
        db.session.commit()
        return product, variant


def test_get_search_and_save_delete(client, app):
    _seed_product(app)
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


def test_search_filter_by_price_range(client, app):
    _seed_product(app, name="Cheap Item", sku="CHE-1", price=5.0)
    _seed_product(app, name="Expensive Item", sku="EXP-1", price=500.0)
    login_as(client, "staff")

    resp = client.get("/search/?q=Item&type=products&min_price=100")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "Expensive Item" in html
    assert "Cheap Item" not in html

    resp2 = client.get("/search/?q=Item&type=products&max_price=10")
    html2 = resp2.data.decode()
    assert "Cheap Item" in html2
    assert "Expensive Item" not in html2


def test_search_filter_by_category(client, app):
    with app.app_context():
        cat = Category(name="Footwear")
        db.session.add(cat)
        db.session.commit()
        _seed_product(app, name="Boot", sku="BOT-1", category=cat)
        _seed_product(app, name="Ball", sku="BAL-1")
        cat_id = cat.id

    login_as(client, "staff")
    resp = client.get(f"/search/?q=&type=products&category_id={cat_id}")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "Boot" in html
    assert "Ball" not in html


def test_search_filter_by_tag(client, app):
    with app.app_context():
        tag = Tag(name="sale")
        db.session.add(tag)
        db.session.commit()
        product = Product(name="Tagged Item", slug="tagged-item", is_published=True)
        db.session.add(product)
        db.session.flush()
        product.tags.append(tag)
        db.session.add(ProductVariant(product_id=product.id, sku="TAG-1", base_price=20.0))
        db.session.add(Product(name="Untagged Item", slug="untagged-item", is_published=True))
        db.session.flush()
        untagged = Product.query.filter_by(slug="untagged-item").first()
        db.session.add(ProductVariant(product_id=untagged.id, sku="UNT-1", base_price=20.0))
        db.session.commit()
        tag_id = tag.id

    login_as(client, "staff")
    resp = client.get(f"/search/?q=Item&type=products&tag_id={tag_id}")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "Tagged Item" in html
    assert "Untagged Item" not in html


def test_search_filter_news_by_date_range(client, app):
    with app.app_context():
        source = NewsSource(name="DateTest", source_type="rss", is_allowed=True, created_by=1)
        db.session.add(source)
        db.session.flush()
        from datetime import datetime
        old_item = NewsItem(
            source_id=source.id, title="Old News", summary="s", file_hash="hash-old",
            ingested_at=datetime(2023, 1, 1),
        )
        new_item = NewsItem(
            source_id=source.id, title="New News", summary="s", file_hash="hash-new",
            ingested_at=datetime(2025, 6, 1),
        )
        db.session.add(old_item)
        db.session.add(new_item)
        db.session.commit()

    login_as(client, "staff")
    resp = client.get("/search/?q=News&type=news&date_from=2025-01-01")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "New News" in html
    assert "Old News" not in html


def test_pin_toggle_saved_search(client, app):
    _seed_product(app, name="PinItem", sku="PIN-1")
    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()

    headers = hmac_headers(staff, "POST", "/search/saved", {"name": "Pinnable"})
    client.post("/search/saved", data={"name": "Pinnable"}, headers=headers)

    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
        saved = SavedSearch.query.filter_by(user_id=staff.id).first()
        assert saved.is_pinned is False or saved.is_pinned == 0

    headers = hmac_headers(staff, "POST", f"/search/saved/{saved.id}/pin")
    resp = client.post(f"/search/saved/{saved.id}/pin", headers=headers)
    assert resp.status_code == 200

    with app.app_context():
        saved = SavedSearch.query.get(saved.id)
        assert saved.is_pinned is True


def test_search_compound_price_and_category(client, app):
    """Products filtered by min_price AND category_id must satisfy both conditions."""
    with app.app_context():
        cat = Category(name="SearchCat")
        db.session.add(cat)
        db.session.flush()
        cat_id = cat.id

        for name, sku, price, use_cat in [
            ("PriceCatExact", "PCE-1", 200.0, True),
            ("PriceCatMatch", "PCM-1", 200.0, False),
            ("PriceCatCheap", "PCC-1", 5.0, True),
        ]:
            p = Product(name=name, slug=sku.lower(), is_published=True)
            db.session.add(p)
            db.session.flush()
            db.session.add(ProductVariant(
                product_id=p.id, sku=sku, base_price=price,
                category_id=cat_id if use_cat else None,
            ))
        db.session.commit()

    login_as(client, "staff")
    resp = client.get(f"/search/?type=products&min_price=100&category_id={cat_id}")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "PriceCatExact" in html
    assert "PriceCatMatch" not in html   # right price, wrong category
    assert "PriceCatCheap" not in html   # right category, wrong price


def test_search_compound_price_and_tag(client, app):
    """Products filtered by max_price AND tag_id must satisfy both conditions."""
    with app.app_context():
        tag = Tag(name="searchtag")
        db.session.add(tag)
        db.session.flush()
        tag_id = tag.id

        for name, sku, price, has_tag in [
            ("TagCheap", "TC-1", 5.0, True),
            ("TagExpensive", "TE-1", 500.0, True),
            ("NoTagCheap", "NTC-1", 5.0, False),
        ]:
            p = Product(name=name, slug=sku.lower(), is_published=True)
            db.session.add(p)
            db.session.flush()
            if has_tag:
                p.tags.append(tag)
            db.session.add(ProductVariant(product_id=p.id, sku=sku, base_price=price))
        db.session.commit()

    login_as(client, "staff")
    resp = client.get(f"/search/?type=products&max_price=10&tag_id={tag_id}")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "TagCheap" in html
    assert "TagExpensive" not in html   # has tag but too expensive
    assert "NoTagCheap" not in html    # right price but no tag


def test_search_compound_category_and_tag(client, app):
    """Products filtered by category_id AND tag_id must satisfy both conditions."""
    with app.app_context():
        cat = Category(name="CatTagCat")
        tag = Tag(name="cattag")
        db.session.add_all([cat, tag])
        db.session.flush()
        cat_id, tag_id = cat.id, tag.id

        for name, sku, has_cat, has_tag in [
            ("CatTagBoth", "CTB-1", True, True),
            ("CatTagOnlyCat", "CTOC-1", True, False),
            ("CatTagOnlyTag", "CTOT-1", False, True),
        ]:
            p = Product(name=name, slug=sku.lower(), is_published=True)
            db.session.add(p)
            db.session.flush()
            if has_tag:
                p.tags.append(tag)
            db.session.add(ProductVariant(
                product_id=p.id, sku=sku, base_price=10.0,
                category_id=cat_id if has_cat else None,
            ))
        db.session.commit()

    login_as(client, "staff")
    resp = client.get(f"/search/?type=products&category_id={cat_id}&tag_id={tag_id}")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "CatTagBoth" in html
    assert "CatTagOnlyCat" not in html
    assert "CatTagOnlyTag" not in html


def test_saved_search_isolation_between_users(client, app):
    _seed_product(app, name="IsolationItem", sku="ISO-1")
    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
    headers = hmac_headers(staff, "POST", "/search/saved", {"name": "StaffSearch"})
    client.post("/search/saved", data={"name": "StaffSearch"}, headers=headers)

    with app.app_context():
        saved = SavedSearch.query.filter_by(user_id=staff.id).first()
        assert saved is not None

    login_as(client, "trainer")
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
    headers = hmac_headers(trainer, "DELETE", f"/search/saved/{saved.id}")
    resp = client.delete(f"/search/saved/{saved.id}", headers=headers)
    assert resp.status_code == 403


def test_all_type_pagination_does_not_drop_results(client, app):
    with app.app_context():
        names = []
        for i in range(30):
            name = f"AllTypeItem{i:02d}"
            names.append(name)
            product = Product(name=name, slug=f"alltype-{i}", is_published=True)
            db.session.add(product)
            db.session.flush()
            db.session.add(ProductVariant(product_id=product.id, sku=f"ALL-{i:02d}", base_price=10.0))
        db.session.commit()

    login_as(client, "staff")
    page1 = client.get("/search/?q=AllTypeItem&type=all&page=1")
    page2 = client.get("/search/?q=AllTypeItem&type=all&page=2")
    assert page1.status_code == 200
    assert page2.status_code == 200

    combined = page1.data.decode() + page2.data.decode()
    for name in names:
        assert name in combined


def test_search_invalid_date_filter_returns_400(client):
    login_as(client, "staff")
    resp = client.get("/search/?type=news&date_from=not-a-date")
    assert resp.status_code == 400
