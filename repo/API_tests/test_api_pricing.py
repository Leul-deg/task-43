from datetime import date, datetime, timedelta

from app.extensions import db
from app.models import PriceRule, Product, ProductVariant, User
from conftest import hmac_headers, login_as


def _booking_dt(hours_ahead=24):
    return (datetime.utcnow() + timedelta(hours=hours_ahead)).strftime("%Y-%m-%dT%H:%M")


def _make_variant(app, sku="PRICE-SKU", price=100.0):
    with app.app_context():
        product = Product(name=f"Pricing {sku}", slug=sku.lower())
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(product_id=product.id, sku=sku, base_price=price)
        db.session.add(variant)
        db.session.commit()
        return variant.id


def _add_rule(app, variant_id, rule_type, value, days_offset_start=-1, days_offset_end=30):
    with app.app_context():
        rule = PriceRule(
            variant_id=variant_id,
            rule_type=rule_type,
            value=value,
            start_date=date.today() + timedelta(days=days_offset_start),
            end_date=date.today() + timedelta(days=days_offset_end),
            min_booking_minutes=60,
            advance_min_hours=2,
            advance_max_days=60,
        )
        db.session.add(rule)
        db.session.commit()
        return rule.id


def test_non_admin_cannot_access_rules(client):
    login_as(client, "staff")
    assert client.get("/pricing/rules").status_code == 403


def test_admin_can_list_rules(client):
    login_as(client, "admin")
    assert client.get("/pricing/rules").status_code == 200


def test_admin_can_create_rule(client, app):
    variant_id = _make_variant(app, "RULE-CREATE")

    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    data = {
        "variant_id": str(variant_id),
        "rule_type": "discount",
        "value": "10",
        "start_date": (date.today() - timedelta(days=1)).strftime("%Y-%m-%d"),
        "end_date": (date.today() + timedelta(days=30)).strftime("%Y-%m-%d"),
        "min_booking_minutes": "60",
        "advance_min_hours": "2",
        "advance_max_days": "60",
    }
    headers = hmac_headers(admin, "POST", "/pricing/rules", data)
    resp = client.post("/pricing/rules", data=data, headers=headers)
    assert resp.status_code == 302

    with app.app_context():
        rule = PriceRule.query.filter_by(variant_id=variant_id, rule_type="discount").first()
        assert rule is not None
        assert rule.value == 10.0


def test_admin_can_update_rule(client, app):
    variant_id = _make_variant(app, "RULE-UPDATE")
    rule_id = _add_rule(app, variant_id, "discount", 5.0)

    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    data = {"rule_type": "discount", "value": "20"}
    headers = hmac_headers(admin, "PUT", f"/pricing/rules/{rule_id}", data)
    resp = client.put(f"/pricing/rules/{rule_id}", data=data, headers=headers)
    assert resp.status_code == 200

    with app.app_context():
        assert PriceRule.query.get(rule_id).value == 20.0


def test_admin_can_delete_rule(client, app):
    variant_id = _make_variant(app, "RULE-DELETE")
    rule_id = _add_rule(app, variant_id, "markup", 5.0)

    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    headers = hmac_headers(admin, "DELETE", f"/pricing/rules/{rule_id}")
    resp = client.delete(f"/pricing/rules/{rule_id}", headers=headers)
    assert resp.status_code == 204

    with app.app_context():
        assert PriceRule.query.get(rule_id) is None


def test_calculate_discount_rule_applied(client, app):
    variant_id = _make_variant(app, "CALC-DISC", price=100.0)
    _add_rule(app, variant_id, "discount", 10.0)

    login_as(client, "staff")
    resp = client.get(
        f"/pricing/calculate?variant_id={variant_id}&quantity=1&booking_datetime={_booking_dt()}"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["unit_price"] == 90.0
    assert data["total"] == 90.0
    assert len(data["applied_rules"]) == 1
    assert data["applied_rules"][0]["type"] == "discount"


def test_calculate_markup_rule_applied(client, app):
    variant_id = _make_variant(app, "CALC-MARK", price=100.0)
    _add_rule(app, variant_id, "markup", 20.0)

    login_as(client, "staff")
    resp = client.get(
        f"/pricing/calculate?variant_id={variant_id}&quantity=2&booking_datetime={_booking_dt()}"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["unit_price"] == 120.0
    assert data["total"] == 240.0


def test_calculate_expired_rule_not_applied(client, app):
    variant_id = _make_variant(app, "CALC-EXP", price=50.0)
    # Rule ended yesterday — not active for any future booking date
    _add_rule(app, variant_id, "discount", 50.0, days_offset_start=-30, days_offset_end=-1)

    login_as(client, "staff")
    resp = client.get(
        f"/pricing/calculate?variant_id={variant_id}&quantity=1&booking_datetime={_booking_dt()}"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    # Expired rule must not reduce the price
    assert data["unit_price"] == 50.0
    assert data["applied_rules"] == []


def test_calculate_compound_discount_then_markup(client, app):
    """Discount applied first, then markup — rules execute in creation order."""
    variant_id = _make_variant(app, "CALC-CMPD", price=100.0)
    # 10% discount → 90, then 10% markup → 99
    _add_rule(app, variant_id, "discount", 10.0)
    _add_rule(app, variant_id, "markup", 10.0)

    login_as(client, "staff")
    resp = client.get(
        f"/pricing/calculate?variant_id={variant_id}&quantity=1&booking_datetime={_booking_dt()}"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert abs(data["unit_price"] - 99.0) < 0.01
    assert len(data["applied_rules"]) == 2
