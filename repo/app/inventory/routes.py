from datetime import datetime, timedelta
from ..pricing.services import validate_booking_window, calculate_effective_price

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm.exc import StaleDataError

from ..decorators import hmac_required, role_required
from ..extensions import db
from ..models import (
    AnomalyAlert,
    AuditLog,
    Batch,
    Bin,
    Product,
    ProductVariant,
    Reservation,
    StockCount,
    User,
    Warehouse,
    utcnow,
)
from ..utils import safe_int, safe_float

inventory_bp = Blueprint("inventory", __name__)


@inventory_bp.route("/", methods=["GET"])
@jwt_required()
@role_required("admin", "inventory_manager", "staff", "trainer", "content_editor")
def index():
    warehouses = Warehouse.query.order_by(Warehouse.name.asc()).all()

    stock_summary = (
        db.session.query(
            ProductVariant.id,
            Product.name,
            ProductVariant.sku,
            db.func.coalesce(db.func.sum(Batch.quantity), 0).label("total_qty"),
        )
        .join(Product, ProductVariant.product_id == Product.id)
        .outerjoin(Batch, Batch.variant_id == ProductVariant.id)
        .group_by(ProductVariant.id, Product.name, ProductVariant.sku)
        .all()
    )

    today = utcnow().date()
    expiring_7 = (
        db.session.query(Batch, ProductVariant, Product, Bin)
        .join(ProductVariant, Batch.variant_id == ProductVariant.id)
        .join(Product, ProductVariant.product_id == Product.id)
        .join(Bin, Batch.bin_id == Bin.id)
        .filter(Batch.expiration_date != None)
        .filter(Batch.expiration_date <= today + timedelta(days=7))
        .order_by(Batch.expiration_date.asc())
        .all()
    )
    expiring_30 = (
        db.session.query(Batch, ProductVariant, Product, Bin)
        .join(ProductVariant, Batch.variant_id == ProductVariant.id)
        .join(Product, ProductVariant.product_id == Product.id)
        .join(Bin, Batch.bin_id == Bin.id)
        .filter(Batch.expiration_date != None)
        .filter(Batch.expiration_date <= today + timedelta(days=30))
        .order_by(Batch.expiration_date.asc())
        .all()
    )

    return render_template(
        "inventory/index.html",
        warehouses=warehouses,
        stock_summary=stock_summary,
        expiring_7=expiring_7,
        expiring_30=expiring_30,
    )


@inventory_bp.route("/warehouses", methods=["GET"])
@jwt_required()
@role_required("admin", "inventory_manager")
def warehouses():
    warehouses = Warehouse.query.order_by(Warehouse.name.asc()).all()
    bins = Bin.query.all()
    return render_template("inventory/warehouses.html", warehouses=warehouses, bins=bins)


@inventory_bp.route("/warehouses", methods=["POST"])
@jwt_required()
@role_required("admin", "inventory_manager")
@hmac_required
def create_warehouse():
    warehouse = Warehouse(
        name=request.form.get("name", "").strip(),
        location=request.form.get("location", "").strip() or None,
    )
    db.session.add(warehouse)
    db.session.commit()
    return redirect(url_for("inventory.warehouses"))


@inventory_bp.route("/warehouses/<int:warehouse_id>/bins", methods=["POST"])
@jwt_required()
@role_required("admin", "inventory_manager")
@hmac_required
def create_bin(warehouse_id):
    Warehouse.query.get_or_404(warehouse_id)
    bin_item = Bin(
        warehouse_id=warehouse_id,
        label=request.form.get("label", "").strip(),
    )
    db.session.add(bin_item)
    db.session.commit()
    return redirect(url_for("inventory.warehouses"))


@inventory_bp.route("/batches", methods=["GET"])
@jwt_required()
@role_required("admin", "inventory_manager", "staff", "trainer", "content_editor")
def batches():
    page = safe_int(request.args.get("page", 1))
    warehouse_id = request.args.get("warehouse_id")
    variant_id = request.args.get("variant_id")
    expiring_within = request.args.get("expiring_within")

    query = (
        db.session.query(Batch, ProductVariant, Product, Bin, Warehouse)
        .join(ProductVariant, Batch.variant_id == ProductVariant.id)
        .join(Product, ProductVariant.product_id == Product.id)
        .join(Bin, Batch.bin_id == Bin.id)
        .join(Warehouse, Bin.warehouse_id == Warehouse.id)
    )

    if warehouse_id:
        query = query.filter(Warehouse.id == safe_int(warehouse_id))
    if variant_id:
        query = query.filter(ProductVariant.id == safe_int(variant_id))
    if expiring_within:
        cutoff = utcnow().date() + timedelta(days=safe_int(expiring_within))
        query = query.filter(Batch.expiration_date != None)
        query = query.filter(Batch.expiration_date <= cutoff)

    pagination = query.order_by(Batch.expiration_date.asc()).paginate(
        page=page, per_page=25, error_out=False
    )

    warehouses = Warehouse.query.order_by(Warehouse.name.asc()).all()
    variants = ProductVariant.query.order_by(ProductVariant.sku.asc()).all()
    bins = Bin.query.all()

    warehouse_lookup = {warehouse.id: warehouse.name for warehouse in warehouses}
    return render_template(
        "inventory/batches.html",
        batches=pagination.items,
        pagination=pagination,
        warehouses=warehouses,
        variants=variants,
        bins=bins,
        warehouse_lookup=warehouse_lookup,
        filters={
            "warehouse_id": warehouse_id,
            "variant_id": variant_id,
            "expiring_within": expiring_within,
        },
    )


@inventory_bp.route("/batches", methods=["POST"])
@jwt_required()
@role_required("inventory_manager")
@hmac_required
def create_batch():
    expiration_value = request.form.get("expiration_date")
    exp_date = None
    if expiration_value:
        try:
            exp_date = datetime.strptime(expiration_value, "%Y-%m-%d").date()
        except ValueError:
            return "Invalid date format. Use YYYY-MM-DD.", 400
    variant_id = safe_int(request.form.get("variant_id"))
    bin_id = safe_int(request.form.get("bin_id"))
    if not ProductVariant.query.get(variant_id):
        return "Invalid variant ID.", 400
    if not Bin.query.get(bin_id):
        return "Invalid bin ID.", 400
    batch = Batch(
        variant_id=variant_id,
        bin_id=bin_id,
        quantity=safe_int(request.form.get("quantity")),
        expiration_date=exp_date,
    )
    db.session.add(batch)
    db.session.commit()
    return redirect(url_for("inventory.batches"))


@inventory_bp.route("/batches/<int:variant_id>/pick", methods=["GET"])
@jwt_required()
@role_required("admin", "inventory_manager", "staff", "trainer", "content_editor")
def pick(variant_id):
    batches = (
        Batch.query.filter_by(variant_id=variant_id)
        .order_by(Batch.expiration_date.asc())
        .all()
    )
    variant = ProductVariant.query.get_or_404(variant_id)
    return render_template("inventory/pick.html", batches=batches, variant=variant)


@inventory_bp.route("/stock-count", methods=["GET"])
@jwt_required()
@role_required("inventory_manager")
def stock_count_form():
    batches = Batch.query.order_by(Batch.received_at.desc()).all()
    return render_template("inventory/stock_count.html", batches=batches)


@inventory_bp.route("/stock-count", methods=["POST"])
@jwt_required()
@role_required("inventory_manager")
@hmac_required
def submit_stock_count():
    batch_id = safe_int(request.form.get("batch_id"))
    expected_qty = safe_int(request.form.get("expected_qty"))
    counted_qty = safe_int(request.form.get("counted_qty"))
    variance = counted_qty - expected_qty
    if expected_qty:
        variance_pct = abs(variance) / expected_qty * 100
    else:
        variance_pct = 100 if counted_qty else 0

    variance_reason = request.form.get("variance_reason", "").strip()
    if (variance_pct > 2 or abs(variance) > 10) and not variance_reason:
        return "Variance reason required.", 400

    count = StockCount(
        batch_id=batch_id,
        expected_qty=expected_qty,
        counted_qty=counted_qty,
        variance=variance,
        variance_pct=variance_pct,
        variance_reason=variance_reason or None,
        counted_by=get_jwt_identity(),
    )
    db.session.add(count)
    db.session.add(
        AuditLog(
            user_id=get_jwt_identity(),
            action="stock_count",
            detail=f"Batch {batch_id} counted",
            ip_address=AuditLog.hash_ip(request.remote_addr),
        )
    )
    db.session.commit()
    return redirect(url_for("inventory.stock_count_form"))


@inventory_bp.route("/reservations", methods=["GET"])
@jwt_required()
@role_required("admin", "inventory_manager", "staff", "trainer", "content_editor")
def reservations():
    identity = get_jwt_identity()
    user = User.query.get(identity) if identity else None
    query = Reservation.query
    if user and user.role not in ["admin", "inventory_manager"]:
        query = query.filter(Reservation.user_id == identity)
    reservations_list = query.order_by(Reservation.held_at.desc()).all()
    return render_template("inventory/reservations.html", reservations=reservations_list)


@inventory_bp.route("/reservations", methods=["POST"])
@jwt_required()
@role_required("admin", "inventory_manager", "staff", "trainer", "content_editor")
@hmac_required
def create_reservation():
    variant_id = safe_int(request.form.get("variant_id"))
    quantity = safe_int(request.form.get("quantity"))
    user_id = get_jwt_identity()
    variant = ProductVariant.query.get(variant_id)
    if not variant:
        return "Variant not found.", 404
    product = Product.query.get(variant.product_id)
    if product and product.purchase_limit and quantity > product.purchase_limit:
        return f"Maximum {product.purchase_limit} units per order.", 400
    booking_date_str = request.form.get("booking_datetime") or request.form.get("booking_date")
    duration_minutes = safe_int(request.form.get("duration_minutes"))
    if not booking_date_str:
        return "Booking datetime is required.", 400
    if not duration_minutes or duration_minutes <= 0:
        return "Booking duration is required.", 400
    try:
        booking_dt = datetime.strptime(booking_date_str, "%Y-%m-%dT%H:%M")
    except ValueError:
        return "Invalid booking date format. Use YYYY-MM-DDTHH:MM.", 400
    valid, reason = validate_booking_window(variant_id, booking_dt, duration_minutes)
    if not valid:
        return reason, 400
    buffer = int(current_app.config.get("OVERBOOKING_BUFFER", 2))

    now = utcnow()
    unit_price, total_price, _ = calculate_effective_price(variant_id, quantity, booking_dt)

    try:
        with db.session.begin_nested():
            total_stock = (
                db.session.query(db.func.coalesce(db.func.sum(Batch.quantity), 0))
                .filter(Batch.variant_id == variant_id)
                .scalar()
            )
            held = (
                db.session.query(db.func.coalesce(db.func.sum(Reservation.quantity), 0))
                .filter(
                    Reservation.variant_id == variant_id,
                    Reservation.status == "held",
                    Reservation.expires_at > now,
                )
                .scalar()
            )
            if held + quantity > total_stock + buffer:
                return "Insufficient stock.", 409

            variant.version += 1
            db.session.add(variant)

            reservation = Reservation(
                variant_id=variant_id,
                user_id=user_id,
                quantity=quantity,
                booking_datetime=booking_dt,
                status="held",
                expires_at=now + timedelta(minutes=20),
                unit_price=unit_price,
                total_price=total_price,
            )
            db.session.add(reservation)

        recent_holds = Reservation.query.filter(
            Reservation.user_id == user_id,
            Reservation.held_at >= now - timedelta(minutes=2),
        ).count()
        if recent_holds >= 5:
            db.session.add(
                AnomalyAlert(
                    user_id=user_id,
                    rule_triggered="frequent_holds",
                    detail="5+ holds within 2 minutes",
                    severity="medium",
                )
            )
        db.session.add(
            AuditLog(
                user_id=user_id,
                action="reservation_created",
                detail=f"Variant: {variant_id} qty: {quantity}",
                ip_address=AuditLog.hash_ip(request.remote_addr),
            )
        )
        db.session.commit()
    except (StaleDataError, OperationalError):
        db.session.rollback()
        return "The system is experiencing heavy load and this item's stock changed. Please try again.", 409
    return "", 201


@inventory_bp.route("/reservations/<int:reservation_id>/confirm", methods=["POST"])
@jwt_required()
@role_required("admin", "inventory_manager")
@hmac_required
def confirm_reservation(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.status != "held":
        return "", 200

    reservation.status = "confirmed"
    reservation.confirmed_at = utcnow()

    remaining = reservation.quantity
    batches = (
        Batch.query.filter_by(variant_id=reservation.variant_id)
        .order_by(Batch.expiration_date.asc())
        .all()
    )
    for batch in batches:
        if remaining <= 0:
            break
        deduction = min(batch.quantity, remaining)
        batch.quantity -= deduction
        remaining -= deduction

    db.session.add(
        AuditLog(
            user_id=get_jwt_identity(),
            action="reservation_confirmed",
            detail=f"Reservation ID: {reservation_id}",
            ip_address=AuditLog.hash_ip(request.remote_addr),
        )
    )
    db.session.commit()
    return "", 200


@inventory_bp.route("/reservations/<int:reservation_id>/release", methods=["POST"])
@jwt_required()
@role_required("admin", "inventory_manager", "staff", "trainer", "content_editor")
@hmac_required
def release_reservation(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    identity = get_jwt_identity()
    if reservation.user_id != identity:
        if identity:
            user = User.query.get(identity)
            if not user or user.role not in ["admin", "inventory_manager"]:
                return abort(403)
    reservation.status = "released"
    db.session.add(
        AuditLog(
            user_id=get_jwt_identity(),
            action="reservation_released",
            detail=f"Reservation ID: {reservation_id}",
            ip_address=AuditLog.hash_ip(request.remote_addr),
        )
    )
    db.session.commit()
    return "", 200
