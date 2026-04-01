from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_jwt_extended import jwt_required

from ..decorators import hmac_required, role_required
from ..extensions import db
from ..models import PriceRule, ProductVariant
from ..utils import safe_int, safe_float
from .services import calculate_effective_price

pricing_bp = Blueprint("pricing", __name__)


@pricing_bp.route("/")
@jwt_required()
@role_required("admin")
def index():
    return redirect(url_for("pricing.rules_index"))


@pricing_bp.route("/rules", methods=["GET"])
@jwt_required()
@role_required("admin")
def rules_index():
    rules = PriceRule.query.order_by(PriceRule.created_at.desc()).all()
    variants = ProductVariant.query.order_by(ProductVariant.sku.asc()).all()
    return render_template("pricing/rules.html", rules=rules, variants=variants)


@pricing_bp.route("/rules", methods=["POST"])
@jwt_required()
@role_required("admin")
@hmac_required
def create_rule():
    try:
        start_date = datetime.strptime(request.form.get("start_date"), "%Y-%m-%d").date()
        end_date = datetime.strptime(request.form.get("end_date"), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return redirect(url_for("pricing.rules_index"))
    rule = PriceRule(
        variant_id=safe_int(request.form.get("variant_id")),
        rule_type=request.form.get("rule_type"),
        value=safe_float(request.form.get("value")),
        start_date=start_date,
        end_date=end_date,
        min_booking_minutes=safe_int(request.form.get("min_booking_minutes", 60)),
        advance_min_hours=safe_int(request.form.get("advance_min_hours", 2)),
        advance_max_days=safe_int(request.form.get("advance_max_days", 60)),
    )
    db.session.add(rule)
    db.session.commit()
    return redirect(url_for("pricing.rules_index"))


@pricing_bp.route("/rules/<int:rule_id>", methods=["PUT"])
@jwt_required()
@role_required("admin")
@hmac_required
def update_rule(rule_id):
    rule = PriceRule.query.get_or_404(rule_id)
    rule.rule_type = request.form.get("rule_type", rule.rule_type)
    rule.value = safe_float(request.form.get("value", rule.value))
    if request.form.get("start_date"):
        rule.start_date = datetime.strptime(request.form.get("start_date"), "%Y-%m-%d").date()
    if request.form.get("end_date"):
        rule.end_date = datetime.strptime(request.form.get("end_date"), "%Y-%m-%d").date()
    rule.min_booking_minutes = safe_int(
        request.form.get("min_booking_minutes", rule.min_booking_minutes)
    )
    rule.advance_min_hours = safe_int(
        request.form.get("advance_min_hours", rule.advance_min_hours)
    )
    rule.advance_max_days = safe_int(
        request.form.get("advance_max_days", rule.advance_max_days)
    )
    db.session.commit()
    return render_template("pricing/partials/rule_row.html", rule=rule)


@pricing_bp.route("/rules/<int:rule_id>", methods=["DELETE"])
@jwt_required()
@role_required("admin")
@hmac_required
def delete_rule(rule_id):
    rule = PriceRule.query.get_or_404(rule_id)
    db.session.delete(rule)
    db.session.commit()
    return "", 204


@pricing_bp.route("/calculate", methods=["GET"])
@jwt_required()
@role_required("admin", "content_editor", "inventory_manager", "trainer", "staff")
def calculate():
    variant_id = safe_int(request.args.get("variant_id"))
    quantity = safe_int(request.args.get("quantity", 1))
    booking_datetime_str = request.args.get("booking_datetime")
    if not booking_datetime_str:
        return jsonify({"error": "booking_datetime is required (YYYY-MM-DDTHH:MM)"}), 400
    try:
        booking_datetime = datetime.strptime(booking_datetime_str, "%Y-%m-%dT%H:%M")
    except ValueError:
        return jsonify({"error": "Invalid booking_datetime format. Use YYYY-MM-DDTHH:MM."}), 400
    unit_price, total, applied_rules = calculate_effective_price(variant_id, quantity, booking_datetime)
    return jsonify(
        {
            "variant_id": variant_id,
            "quantity": quantity,
            "unit_price": unit_price,
            "total": total,
            "applied_rules": applied_rules,
        }
    )
