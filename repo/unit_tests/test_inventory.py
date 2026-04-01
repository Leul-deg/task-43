from datetime import datetime, timedelta

from app.extensions import db
from app.models import Batch, Bin, PriceRule, Product, ProductVariant, Reservation, Warehouse, User
from app.pricing.services import calculate_effective_price
from conftest import hmac_headers, login_as


def _setup_inventory(app):
    with app.app_context():
        warehouse = Warehouse(name="Main")
        db.session.add(warehouse)
        db.session.flush()
        bin_item = Bin(warehouse_id=warehouse.id, label="A1")
        db.session.add(bin_item)
        product = Product(name="Ball", slug="ball")
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(product_id=product.id, sku="BALL-1", base_price=10)
        db.session.add(variant)
        db.session.commit()
        return warehouse, bin_item, variant


def test_stock_total_across_batches(client, app):
    warehouse, bin_item, variant = _setup_inventory(app)
    with app.app_context():
        db.session.add(Batch(variant_id=variant.id, bin_id=bin_item.id, quantity=5))
        db.session.add(Batch(variant_id=variant.id, bin_id=bin_item.id, quantity=7))
        db.session.commit()

    login_as(client, "staff")
    response = client.get("/inventory/")
    assert response.status_code == 200
    assert b"12" in response.data


def test_fefo_order(client, app):
    warehouse, bin_item, variant = _setup_inventory(app)
    with app.app_context():
        batch1 = Batch(
            variant_id=variant.id,
            bin_id=bin_item.id,
            quantity=5,
            expiration_date=datetime.utcnow().date() + timedelta(days=5),
        )
        batch2 = Batch(
            variant_id=variant.id,
            bin_id=bin_item.id,
            quantity=5,
            expiration_date=datetime.utcnow().date() + timedelta(days=1),
        )
        db.session.add_all([batch1, batch2])
        db.session.commit()

    login_as(client, "staff")
    response = client.get(f"/inventory/batches/{variant.id}/pick")
    assert response.status_code == 200
    first_index = response.data.find(f"<td>{batch2.id}</td>".encode())
    second_index = response.data.find(f"<td>{batch1.id}</td>".encode())
    assert first_index != -1 and second_index != -1
    assert first_index < second_index


def test_reservation_hold_and_overbooking(client, app):
    warehouse, bin_item, variant = _setup_inventory(app)
    with app.app_context():
        db.session.add(Batch(variant_id=variant.id, bin_id=bin_item.id, quantity=5))
        db.session.commit()
        user = User.query.filter_by(username="test_staff").first()

    login_as(client, "staff")

    # stock=5, buffer=2 → max holdable = 7
    # Hold 7 units (at the overbooking limit) → should succeed
    data1 = {
        "variant_id": str(variant.id),
        "quantity": "7",
        "booking_date": (datetime.utcnow() + timedelta(days=10)).strftime("%Y-%m-%dT10:00"),
        "duration_minutes": "60",
    }
    headers = hmac_headers(user, "POST", "/inventory/reservations", data1)
    response = client.post(
        "/inventory/reservations",
        data=data1,
        headers=headers,
    )
    assert response.status_code == 201

    # Hold 1 more → 7+1=8 > 7 → should be rejected
    data2 = {
        "variant_id": str(variant.id),
        "quantity": "1",
        "booking_date": (datetime.utcnow() + timedelta(days=10)).strftime("%Y-%m-%dT10:00"),
        "duration_minutes": "60",
    }
    headers = hmac_headers(user, "POST", "/inventory/reservations", data2)
    response = client.post(
        "/inventory/reservations",
        data=data2,
        headers=headers,
    )
    assert response.status_code == 409
    with app.app_context():
        reservation = Reservation.query.order_by(Reservation.id.desc()).first()
        assert reservation.expires_at <= datetime.utcnow() + timedelta(minutes=20, seconds=10)


def test_stock_count_variance_requires_reason(client, app):
    warehouse, bin_item, variant = _setup_inventory(app)
    with app.app_context():
        batch = Batch(variant_id=variant.id, bin_id=bin_item.id, quantity=100)
        db.session.add(batch)
        db.session.commit()
        user = User.query.filter_by(username="test_inventory").first()

    login_as(client, "inventory_manager")

    data1 = {"batch_id": str(batch.id), "expected_qty": "100", "counted_qty": "104"}
    headers1 = hmac_headers(user, "POST", "/inventory/stock-count", data1)
    response = client.post(
        "/inventory/stock-count",
        data=data1,
        headers=headers1,
    )
    assert response.status_code == 400

    data2 = {"batch_id": str(batch.id), "expected_qty": "100", "counted_qty": "101"}
    headers2 = hmac_headers(user, "POST", "/inventory/stock-count", data2)
    response = client.post(
        "/inventory/stock-count",
        data=data2,
        headers=headers2,
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_reservation_price_matches_quote(app, client):
    warehouse, bin_item, variant = _setup_inventory(app)
    with app.app_context():
        db.session.add(Batch(variant_id=variant.id, bin_id=bin_item.id, quantity=100))
        rule_date = (datetime.utcnow() + timedelta(days=5)).date()
        db.session.add(
            PriceRule(
                variant_id=variant.id,
                rule_type="discount",
                value=15.0,
                start_date=rule_date,
                end_date=rule_date,
                advance_min_hours=2,
                advance_max_days=30,
                min_booking_minutes=60,
            )
        )
        db.session.commit()
        user = User.query.filter_by(username="test_staff").first()

    booking_dt = rule_date.strftime("%Y-%m-%dT10:00")
    booking_datetime = datetime.strptime(booking_dt, "%Y-%m-%dT%H:%M")
    login_as(client, "staff")

    quote_unit, quote_total, _ = calculate_effective_price(variant.id, 2, booking_datetime)
    assert quote_unit == 8.5
    assert quote_total == 17.0

    data = {
        "variant_id": str(variant.id),
        "quantity": "2",
        "booking_datetime": booking_dt,
        "duration_minutes": "60",
    }
    headers = hmac_headers(user, "POST", "/inventory/reservations", data)
    resp = client.post("/inventory/reservations", data=data, headers=headers)
    assert resp.status_code == 201

    with app.app_context():
        reservation = Reservation.query.filter_by(variant_id=variant.id, status="held").first()
        assert reservation.unit_price == quote_unit
        assert reservation.total_price == quote_total
        assert reservation.booking_datetime is not None


def test_concurrent_reservations_respect_stock_limit(app, client):
    """Sequential holds that together exceed stock+buffer must not both succeed.

    This verifies the overbooking guard rejects a second hold once the
    cumulative held quantity exceeds total_stock + buffer.
    """
    warehouse, bin_item, variant = _setup_inventory(app)
    with app.app_context():
        db.session.add(Batch(variant_id=variant.id, bin_id=bin_item.id, quantity=5))
        db.session.commit()
        user = User.query.filter_by(username="test_staff").first()

    login_as(client, "staff")
    booking_dt = (datetime.utcnow() + timedelta(days=10)).strftime("%Y-%m-%dT10:00")

    # First hold: 6 units against stock=5, buffer=2 → held+qty=6 ≤ 7 → 201
    data1 = {
        "variant_id": str(variant.id),
        "quantity": "6",
        "booking_date": booking_dt,
        "duration_minutes": "60",
    }
    headers1 = hmac_headers(user, "POST", "/inventory/reservations", data1)
    resp1 = client.post("/inventory/reservations", data=data1, headers=headers1)
    assert resp1.status_code == 201

    # Second hold: 2 more → held=6+2=8 > 7 → 409
    data2 = {
        "variant_id": str(variant.id),
        "quantity": "2",
        "booking_date": booking_dt,
        "duration_minutes": "60",
    }
    headers2 = hmac_headers(user, "POST", "/inventory/reservations", data2)
    resp2 = client.post("/inventory/reservations", data=data2, headers=headers2)
    assert resp2.status_code == 409

    # Verify only one reservation exists
    with app.app_context():
        held = Reservation.query.filter_by(
            variant_id=variant.id, status="held"
        ).count()
        assert held == 1


def test_concurrent_reservations_true_parallel(tmp_path):
    """Two threads hit /inventory/reservations simultaneously against a
    file-based SQLite database, proving the overbooking guard works under
    real concurrency contention.
    """
    import hashlib as _hl
    import hmac as _hm
    import os
    import threading
    import uuid as _uu
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import timezone
    from urllib.parse import urlencode

    from app import create_app
    from app.config import TestConfig
    from app.extensions import db as _db
    from app.models import Batch, Bin, Product, ProductVariant, Reservation, User, Warehouse

    db_file = tmp_path / "conc.db"

    class ConcConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"

    os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing")
    os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-for-testing")
    os.environ.setdefault("HMAC_SECRET", "test-hmac-secret")
    os.environ.setdefault("ADMIN_PASSWORD", "SecureTestPass123!")

    test_app = create_app(config_class=ConcConfig)

    with test_app.app_context():
        _db.create_all()
        admin = User(username="c_admin", role="admin")
        admin.set_password("TestPassword123!")
        staff = User(username="c_staff", role="staff")
        staff.set_password("TestPassword123!")
        _db.session.add_all([admin, staff])
        _db.session.flush()

        wh = Warehouse(name="CW")
        _db.session.add(wh)
        _db.session.flush()
        bn = Bin(warehouse_id=wh.id, label="CB1")
        _db.session.add(bn)
        _db.session.flush()
        prod = Product(name="ConcProd", slug="conc-prod")
        _db.session.add(prod)
        _db.session.flush()
        var = ProductVariant(product_id=prod.id, sku="CONC-1", base_price=10.0)
        _db.session.add(var)
        _db.session.flush()
        _db.session.add(Batch(variant_id=var.id, bin_id=bn.id, quantity=5))
        _db.session.commit()

        hmac_key = staff.get_hmac_key()
        vid = var.id

    booking_dt = (datetime.utcnow() + timedelta(days=10)).strftime("%Y-%m-%dT10:00")
    barrier = threading.Barrier(2, timeout=10)
    results = {}

    def _sign(key, method, path, data):
        body = urlencode(sorted(data.items()), doseq=True)
        bh = _hl.sha256(body.encode()).hexdigest()
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        nonce = str(_uu.uuid4())
        sig = _hm.new(
            key.encode(), f"{method}{path}{ts}{bh}{nonce}".encode(), _hl.sha256
        ).hexdigest()
        return {"X-Signature": sig, "X-Timestamp": ts, "X-Nonce": nonce}

    def reserve(tid):
        c = test_app.test_client()
        c.post(
            "/auth/login",
            data={"username": "c_staff", "password": "TestPassword123!"},
        )
        data = {
            "variant_id": str(vid),
            "quantity": "5",
            "booking_date": booking_dt,
            "duration_minutes": "60",
        }
        hdrs = _sign(hmac_key, "POST", "/inventory/reservations", data)
        barrier.wait()
        resp = c.post("/inventory/reservations", data=data, headers=hdrs)
        results[tid] = resp.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(reserve, i) for i in range(2)]
        for f in as_completed(futs):
            f.result()

    codes = list(results.values())
    assert codes.count(201) <= 1, f"Both reservations succeeded: {codes}"
    assert all(c in (201, 409) for c in codes), f"Unexpected status codes: {codes}"

    with test_app.app_context():
        held = Reservation.query.filter_by(variant_id=vid, status="held").count()
        assert held <= 1
