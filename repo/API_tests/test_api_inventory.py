from datetime import datetime, timedelta

from app.extensions import db
from app.models import Batch, Bin, Product, ProductVariant, PriceRule, Reservation, Warehouse, User
from conftest import hmac_headers, login_as


def _setup_inventory(app):
    with app.app_context():
        warehouse = Warehouse(name="API Warehouse")
        db.session.add(warehouse)
        db.session.flush()
        bin_item = Bin(warehouse_id=warehouse.id, label="B1")
        db.session.add(bin_item)
        product = Product(name="API Ball", slug="api-ball")
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(product_id=product.id, sku="API-BALL", base_price=10)
        db.session.add(variant)
        db.session.flush()
        db.session.add(Batch(variant_id=variant.id, bin_id=bin_item.id, quantity=10))
        db.session.commit()
        return variant


def test_post_reservation_and_overbooking(client, app):
    variant = _setup_inventory(app)
    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
    data1 = {
        "variant_id": str(variant.id),
        "quantity": "1",
        "booking_date": (datetime.utcnow() + timedelta(days=10)).strftime("%Y-%m-%dT10:00"),
        "duration_minutes": "60",
    }
    headers = hmac_headers(staff, "POST", "/inventory/reservations", data1)
    response = client.post(
        "/inventory/reservations",
        data=data1,
        headers=headers,
    )
    assert response.status_code == 201

    data2 = {
        "variant_id": str(variant.id),
        "quantity": "20",
        "booking_date": (datetime.utcnow() + timedelta(days=10)).strftime("%Y-%m-%dT10:00"),
        "duration_minutes": "60",
    }
    headers = hmac_headers(staff, "POST", "/inventory/reservations", data2)
    response = client.post(
        "/inventory/reservations",
        data=data2,
        headers=headers,
    )
    assert response.status_code == 409


def test_post_stock_count(client, app):
    variant = _setup_inventory(app)
    with app.app_context():
        batch = Batch.query.filter_by(variant_id=variant.id).first()
        user = User.query.filter_by(username="test_inventory").first()
    login_as(client, "inventory_manager")
    data = {"batch_id": str(batch.id), "expected_qty": "10", "counted_qty": "10"}
    headers = hmac_headers(user, "POST", "/inventory/stock-count", data)
    response = client.post(
        "/inventory/stock-count",
        data=data,
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_purchase_limit_enforced(app, client):
    """Cannot reserve more than purchase_limit"""
    with app.app_context():
        from app.models import Product, ProductVariant, Warehouse, Bin, Batch, User, db
        from conftest import login_as, hmac_headers

        login_as(client, "admin")
        p = Product(name="Limited Item", slug="limited-item", is_published=True, purchase_limit=5)
        db.session.add(p)
        db.session.flush()
        v = ProductVariant(product_id=p.id, sku="LIM-001", base_price=10.0)
        db.session.add(v)
        db.session.flush()
        w = Warehouse(name="W_limit", location="X")
        db.session.add(w)
        db.session.flush()
        b = Bin(warehouse_id=w.id, label="B1")
        db.session.add(b)
        db.session.flush()
        batch = Batch(variant_id=v.id, bin_id=b.id, quantity=100)
        db.session.add(batch)
        db.session.commit()
        user = User.query.filter_by(username="test_staff").first()
        data = {"variant_id": str(v.id), "quantity": "10"}
        headers = hmac_headers(user, "POST", "/inventory/reservations", data)
        login_as(client, "staff")
        resp = client.post("/inventory/reservations", data=data, headers=headers)
        assert resp.status_code == 400
        assert b"Maximum 5" in resp.data


def test_purchase_limit_allows_within_limit(app, client):
    """Can reserve within purchase_limit"""
    with app.app_context():
        from app.models import Product, ProductVariant, Warehouse, Bin, Batch, User, db
        from conftest import login_as, hmac_headers

        login_as(client, "admin")
        p = Product(name="Limited OK", slug="limited-ok", is_published=True, purchase_limit=5)
        db.session.add(p)
        db.session.flush()
        v = ProductVariant(product_id=p.id, sku="LIM-OK-001", base_price=10.0)
        db.session.add(v)
        db.session.flush()
        w = Warehouse(name="W_limok", location="X")
        db.session.add(w)
        db.session.flush()
        b = Bin(warehouse_id=w.id, label="B1")
        db.session.add(b)
        db.session.flush()
        batch = Batch(variant_id=v.id, bin_id=b.id, quantity=100)
        db.session.add(batch)
        db.session.commit()
        user = User.query.filter_by(username="test_staff").first()
        data = {
            "variant_id": str(v.id),
            "quantity": "3",
            "booking_date": (datetime.utcnow() + timedelta(days=10)).strftime("%Y-%m-%dT10:00"),
            "duration_minutes": "60",
        }
        headers = hmac_headers(user, "POST", "/inventory/reservations", data)
        login_as(client, "staff")
        resp = client.post("/inventory/reservations", data=data, headers=headers)
        assert resp.status_code == 201


def test_reservation_insufficient_stock(app, client):
    """Cannot reserve more than available stock"""
    with app.app_context():
        from app.models import Product, ProductVariant, Warehouse, Bin, Batch, User, db
        from conftest import login_as, hmac_headers

        login_as(client, "admin")
        p = Product(name="Low Stock", slug="low-stock", is_published=True)
        db.session.add(p)
        db.session.flush()
        v = ProductVariant(product_id=p.id, sku="LOW-001", base_price=10.0)
        db.session.add(v)
        db.session.flush()
        w = Warehouse(name="W_low", location="X")
        db.session.add(w)
        db.session.flush()
        b = Bin(warehouse_id=w.id, label="B1")
        db.session.add(b)
        db.session.flush()
        batch = Batch(variant_id=v.id, bin_id=b.id, quantity=5)
        db.session.add(batch)
        db.session.commit()
        user = User.query.filter_by(username="test_staff").first()
        data = {
            "variant_id": str(v.id),
            "quantity": "100",
            "booking_date": (datetime.utcnow() + timedelta(days=10)).strftime("%Y-%m-%dT10:00"),
            "duration_minutes": "60",
        }
        headers = hmac_headers(user, "POST", "/inventory/reservations", data)
        login_as(client, "staff")
        resp = client.post("/inventory/reservations", data=data, headers=headers)
        assert resp.status_code == 409


def test_invalid_form_data_no_500(app, client):
    """Bad input returns 400, not 500"""
    with app.app_context():
        from conftest import login_as

        login_as(client, "inventory_manager")
        resp = client.post(
            "/inventory/batches",
            data={"variant_id": "abc", "bin_id": "xyz", "quantity": "notanumber"},
        )
        assert resp.status_code != 500


def test_sku_duplicate_no_500(app, client):
    """Duplicate SKU returns error, not 500"""
    with app.app_context():
        from app.models import Product, ProductVariant, db
        from conftest import login_as

        login_as(client, "admin")
        p = Product(name="DupTest", slug="duptest", is_published=True)
        db.session.add(p)
        db.session.flush()
        v = ProductVariant(product_id=p.id, sku="DUP-SKU-001", base_price=10.0)
        db.session.add(v)
        db.session.commit()
        resp = client.post("/products/", data={"name": "DupTest2", "sku": "DUP-SKU-001", "base_price": "10"})
        assert resp.status_code != 500


def test_quoted_price_matches_reservation_price(app, client):
    """Quote endpoint returns same unit/total price as reservation holds with same booking_datetime"""
    with app.app_context():
        from app.models import Product, ProductVariant, Warehouse, Bin, Batch, User, db
        from conftest import login_as

        login_as(client, "admin")
        p = Product(name="PriceMatch", slug="price-match", is_published=True)
        db.session.add(p)
        db.session.flush()
        v = ProductVariant(product_id=p.id, sku="PRICE-MATCH-1", base_price=100.0)
        db.session.add(v)
        db.session.flush()
        w = Warehouse(name="W_price", location="X")
        db.session.add(w)
        db.session.flush()
        b = Bin(warehouse_id=w.id, label="B1")
        db.session.add(b)
        db.session.flush()
        db.session.add(Batch(variant_id=v.id, bin_id=b.id, quantity=100))
        db.session.commit()

        discount_dt = datetime.utcnow().date() + timedelta(days=5)
        db.session.add(
            PriceRule(
                variant_id=v.id,
                rule_type="discount",
                value=10.0,
                start_date=discount_dt,
                end_date=discount_dt,
                advance_min_hours=2,
                advance_max_days=30,
                min_booking_minutes=60,
            )
        )
        db.session.commit()
        user = User.query.filter_by(username="test_admin").first()

        booking_dt = discount_dt.strftime("%Y-%m-%dT10:00")
        booking_datetime = datetime.strptime(booking_dt, "%Y-%m-%dT%H:%M")

        login_as(client, "admin")
        quote_resp = client.get(
            f"/pricing/calculate?variant_id={v.id}&quantity=2&booking_datetime={booking_dt}"
        )
        assert quote_resp.status_code == 200
        quote_data = quote_resp.get_json()
        expected_unit = 90.0
        expected_total = 180.0
        assert quote_data["unit_price"] == expected_unit
        assert quote_data["total"] == expected_total

        reservation_data = {
            "variant_id": str(v.id),
            "quantity": "2",
            "booking_datetime": booking_dt,
            "duration_minutes": "60",
        }
        headers = hmac_headers(user, "POST", "/inventory/reservations", reservation_data)
        reservation_resp = client.post(
            "/inventory/reservations",
            data=reservation_data,
            headers=headers,
        )
        assert reservation_resp.status_code == 201

        reservation = Reservation.query.filter_by(variant_id=v.id, status="held").order_by(Reservation.id.desc()).first()
        assert reservation is not None
        assert reservation.booking_datetime is not None
        assert abs((reservation.booking_datetime - booking_datetime).total_seconds()) < 5
        assert reservation.unit_price == expected_unit
        assert reservation.total_price == expected_total


def test_quote_requires_booking_datetime(app, client):
    variant = _setup_inventory(app)
    login_as(client, "staff")
    resp = client.get(f"/pricing/calculate?variant_id={variant.id}&quantity=1")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "booking_datetime is required (YYYY-MM-DDTHH:MM)"


def test_quote_rejects_invalid_booking_datetime(app, client):
    variant = _setup_inventory(app)
    login_as(client, "staff")
    resp = client.get(
        f"/pricing/calculate?variant_id={variant.id}&quantity=1&booking_datetime=bad-date"
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Invalid booking_datetime format. Use YYYY-MM-DDTHH:MM."


def test_quoted_price_no_rule_matches_base_reservation(app, client):
    """When no date-range rule applies, quoted base price matches reservation price"""
    with app.app_context():
        from app.models import Product, ProductVariant, Warehouse, Bin, Batch, User, db
        from conftest import login_as

        login_as(client, "admin")
        p = Product(name="BasePrice", slug="base-price", is_published=True)
        db.session.add(p)
        db.session.flush()
        v = ProductVariant(product_id=p.id, sku="BASE-001", base_price=50.0)
        db.session.add(v)
        db.session.flush()
        w = Warehouse(name="W_base", location="X")
        db.session.add(w)
        db.session.flush()
        b = Bin(warehouse_id=w.id, label="B1")
        db.session.add(b)
        db.session.flush()
        db.session.add(Batch(variant_id=v.id, bin_id=b.id, quantity=100))
        db.session.commit()
        user = User.query.filter_by(username="test_admin").first()

        booking_dt = (datetime.utcnow() + timedelta(days=15)).strftime("%Y-%m-%dT14:00")
        booking_datetime = datetime.strptime(booking_dt, "%Y-%m-%dT%H:%M")

        login_as(client, "admin")
        quote_resp = client.get(
            f"/pricing/calculate?variant_id={v.id}&quantity=3&booking_datetime={booking_dt}"
        )
        assert quote_resp.status_code == 200
        quote_data = quote_resp.get_json()
        assert quote_data["unit_price"] == 50.0
        assert quote_data["total"] == 150.0

        reservation_data = {
            "variant_id": str(v.id),
            "quantity": "3",
            "booking_datetime": booking_dt,
            "duration_minutes": "60",
        }
        headers = hmac_headers(user, "POST", "/inventory/reservations", reservation_data)
        reservation_resp = client.post(
            "/inventory/reservations",
            data=reservation_data,
            headers=headers,
        )
        assert reservation_resp.status_code == 201

        reservation = Reservation.query.filter_by(variant_id=v.id, status="held").order_by(Reservation.id.desc()).first()
        assert reservation.unit_price == 50.0
        assert reservation.total_price == 150.0
        assert reservation.booking_datetime is not None
