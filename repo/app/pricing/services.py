from datetime import datetime, timedelta
from ..models import PriceRule, ProductVariant, TieredPrice, utcnow


def calculate_effective_price(variant_id, quantity=1, booking_datetime=None):
    variant = ProductVariant.query.get(variant_id)
    if not variant:
        return None, None, []

    unit_price = variant.base_price
    tier = (
        TieredPrice.query.filter(
            TieredPrice.variant_id == variant_id, TieredPrice.min_quantity <= quantity
        )
        .order_by(TieredPrice.min_quantity.desc())
        .first()
    )
    if tier:
        unit_price = tier.unit_price

    booking_date = (booking_datetime or utcnow()).date()
    rules = (
        PriceRule.query.filter(
            PriceRule.variant_id == variant_id,
            PriceRule.start_date <= booking_date,
            PriceRule.end_date >= booking_date,
        )
        .order_by(PriceRule.created_at.asc())
        .all()
    )

    applied_rules = []
    for rule in rules:
        if rule.rule_type == "discount":
            unit_price = unit_price * (1 - (rule.value / 100))
        elif rule.rule_type == "markup":
            unit_price = unit_price * (1 + (rule.value / 100))
        applied_rules.append(
            {
                "id": rule.id,
                "type": rule.rule_type,
                "value": rule.value,
            }
        )

    total = unit_price * quantity
    return unit_price, total, applied_rules


def validate_booking_window(variant_id, requested_datetime, duration_minutes=None):
    rules = PriceRule.query.filter(PriceRule.variant_id == variant_id).all()
    if rules:
        min_hours = max(rule.advance_min_hours for rule in rules)
        max_days = min(rule.advance_max_days for rule in rules)
        min_minutes = max(rule.min_booking_minutes for rule in rules)
    else:
        min_hours = 2
        max_days = 60
        min_minutes = 60

    now = utcnow()
    if requested_datetime < now + timedelta(hours=min_hours):
        return False, "Booking is too soon."
    if requested_datetime > now + timedelta(days=max_days):
        return False, "Booking is too far in advance."
    if duration_minutes is not None and duration_minutes < min_minutes:
        return False, f"Minimum booking length is {min_minutes} minutes."
    return True, ""
