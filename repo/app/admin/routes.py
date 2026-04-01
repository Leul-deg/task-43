from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_jwt_extended import get_jwt_identity, jwt_required

from ..decorators import hmac_required, role_required
from ..extensions import db
from ..utils import safe_int
from ..models import AnomalyAlert, AuditLog, User, utcnow

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/", methods=["GET"])
@jwt_required()
@role_required("admin")
def index():
    return render_template("admin/index.html")


@admin_bp.route("/anomalies", methods=["GET"])
@jwt_required()
@role_required("admin")
def anomalies():
    page = safe_int(request.args.get("page"), 1)
    reviewed = request.args.get("reviewed")
    sort = request.args.get("sort", "date")

    query = AnomalyAlert.query
    if reviewed == "true":
        query = query.filter(AnomalyAlert.is_reviewed.is_(True))
    elif reviewed == "false":
        query = query.filter(AnomalyAlert.is_reviewed.is_(False))

    if sort == "severity":
        query = query.order_by(
            db.case(
                (AnomalyAlert.severity == "high", 1),
                (AnomalyAlert.severity == "medium", 2),
                (AnomalyAlert.severity == "low", 3),
                else_=4,
            ),
            AnomalyAlert.created_at.desc(),
        )
    else:
        query = query.order_by(AnomalyAlert.created_at.desc())

    pagination = query.paginate(page=page, per_page=25, error_out=False)
    return render_template(
        "admin/anomalies.html",
        anomalies=pagination.items,
        pagination=pagination,
        filters={"reviewed": reviewed, "sort": sort},
    )


@admin_bp.route("/anomalies/<int:alert_id>/review", methods=["POST"])
@jwt_required()
@role_required("admin")
@hmac_required
def review_anomaly(alert_id):
    alert = AnomalyAlert.query.get_or_404(alert_id)
    alert.is_reviewed = True
    alert.reviewed_by = get_jwt_identity()
    alert.reviewed_at = utcnow()
    db.session.commit()
    return render_template("admin/partials/anomaly_row.html", alert=alert)


@admin_bp.route("/audit-log", methods=["GET"])
@jwt_required()
@role_required("admin")
def audit_log():
    page = safe_int(request.args.get("page"), 1)
    action = request.args.get("action")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    query = AuditLog.query
    if action:
        query = query.filter(AuditLog.action == action)
    if date_from:
        query = query.filter(AuditLog.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
    if date_to:
        query = query.filter(AuditLog.created_at <= datetime.strptime(date_to, "%Y-%m-%d"))

    pagination = query.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=25, error_out=False
    )
    logs = pagination.items

    user_ids = [log.user_id for log in logs if log.user_id]
    users = User.query.filter(User.id.in_(user_ids)).all()
    user_map = {u.id: u.username for u in users}

    entries = []
    for log in logs:
        entries.append(
            {
                "log": log,
                "username": user_map.get(log.user_id, ""),
                "ip": log.ip_address,
            }
        )

    return render_template(
        "admin/audit_log.html",
        entries=entries,
        pagination=pagination,
        filters={"action": action, "date_from": date_from, "date_to": date_to},
    )


@admin_bp.route("/users", methods=["GET"])
@jwt_required()
@role_required("admin")
def users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users)


@admin_bp.route("/users", methods=["POST"])
@jwt_required()
@role_required("admin")
@hmac_required
def create_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "staff")
    if len(password) < 12:
        flash("Password must be at least 12 characters.", "danger")
        return redirect(url_for("admin.users"))

    if User.query.filter_by(username=username).first():
        flash("Username already exists.", "danger")
        return redirect(url_for("admin.users"))

    user = User(username=username, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.add(
        AuditLog(
            user_id=get_jwt_identity(),
            action="user_created",
            detail=f"User: {username} role: {role}",
            ip_address=AuditLog.hash_ip(request.remote_addr),
        )
    )
    db.session.commit()
    flash("User created.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/lock", methods=["POST"])
@jwt_required()
@role_required("admin")
@hmac_required
def lock_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_locked = True
    user.locked_until = datetime(2099, 12, 31)
    db.session.add(
        AuditLog(
            user_id=get_jwt_identity(),
            action="user_locked",
            detail=f"User ID: {user_id}",
            ip_address=AuditLog.hash_ip(request.remote_addr),
        )
    )
    db.session.commit()
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/unlock", methods=["POST"])
@jwt_required()
@role_required("admin")
@hmac_required
def unlock_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_locked = False
    user.locked_until = None
    user.failed_attempts = 0
    db.session.add(
        AuditLog(
            user_id=get_jwt_identity(),
            action="user_unlocked",
            detail=f"User ID: {user_id}",
            ip_address=AuditLog.hash_ip(request.remote_addr),
        )
    )
    db.session.commit()
    return redirect(url_for("admin.users"))
