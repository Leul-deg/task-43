from datetime import datetime, timedelta

from app.extensions import db
from app.models import PriceRule, Product, ProductVariant
from app.pricing.services import calculate_effective_price, validate_booking_window


def _create_variant():
    product = Product(name="Pricing", slug="pricing")
    db.session.add(product)
    db.session.flush()
    variant = ProductVariant(product_id=product.id, sku="P-1", base_price=100)
    db.session.add(variant)
    db.session.commit()
    return variant


def test_base_price(app):
    with app.app_context():
        variant = _create_variant()
        unit, total, rules = calculate_effective_price(variant.id, 1)
        assert unit == 100
        assert total == 100


def test_discount_and_markup(app):
    with app.app_context():
        variant = _create_variant()
        db.session.add(
            PriceRule(
                variant_id=variant.id,
                rule_type="discount",
                value=10,
                start_date=datetime.utcnow().date(),
                end_date=datetime.utcnow().date() + timedelta(days=1),
            )
        )
        db.session.add(
            PriceRule(
                variant_id=variant.id,
                rule_type="markup",
                value=10,
                start_date=datetime.utcnow().date(),
                end_date=datetime.utcnow().date() + timedelta(days=1),
            )
        )
        db.session.commit()
        unit, total, _ = calculate_effective_price(variant.id, 1)
        assert round(unit, 2) == 99.0


def test_expired_rule_ignored(app):
    with app.app_context():
        variant = _create_variant()
        db.session.add(
            PriceRule(
                variant_id=variant.id,
                rule_type="discount",
                value=50,
                start_date=datetime.utcnow().date() - timedelta(days=5),
                end_date=datetime.utcnow().date() - timedelta(days=1),
            )
        )
        db.session.commit()
        unit, total, _ = calculate_effective_price(variant.id, 1)
        assert unit == 100


def test_booking_window(app):
    with app.app_context():
        variant = _create_variant()
        db.session.add(
            PriceRule(
                variant_id=variant.id,
                rule_type="discount",
                value=5,
                start_date=datetime.utcnow().date(),
                end_date=datetime.utcnow().date() + timedelta(days=5),
                advance_min_hours=2,
                advance_max_days=10,
            )
        )
        db.session.commit()

        too_soon = datetime.utcnow() + timedelta(hours=1)
        valid, reason = validate_booking_window(variant.id, too_soon)
        assert valid is False

        too_far = datetime.utcnow() + timedelta(days=20)
        valid, reason = validate_booking_window(variant.id, too_far)
        assert valid is False

        ok = datetime.utcnow() + timedelta(hours=3)
        valid, reason = validate_booking_window(variant.id, ok)
        assert valid is True


def test_default_booking_window(app):
    with app.app_context():
        variant = _create_variant()

        now = datetime.utcnow()

        one_hour = now + timedelta(hours=1)
        valid, reason = validate_booking_window(variant.id, one_hour, duration_minutes=60)
        assert valid is False

        sixty_one_days = now + timedelta(days=61)
        valid, reason = validate_booking_window(variant.id, sixty_one_days, duration_minutes=60)
        assert valid is False

        three_hours = now + timedelta(hours=3)
        valid, reason = validate_booking_window(variant.id, three_hours, duration_minutes=30)
        assert valid is False

        valid, reason = validate_booking_window(variant.id, three_hours, duration_minutes=60)
        assert valid is True
