import logging
import re
from datetime import datetime, timedelta

import hashlib
import hmac as hmac_mod
import secrets

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
    set_access_cookies,
    set_refresh_cookies,
    unset_jwt_cookies,
)

from ..decorators import hmac_required
from ..extensions import db, limiter
from ..models import AnomalyAlert, AuditLog, User, utcnow
from .forms import LoginForm

auth_bp = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data
        user = User.query.filter_by(username=username).first()
        now = utcnow()

        if user and user.is_account_locked():
            flash("Account is locked. Try again in 15 minutes.", "warning")
            return render_template("auth/login.html", form=form), 423

        if user and user.locked_until and user.locked_until <= now:
            user.locked_until = None
            user.is_locked = False
            user.failed_attempts = 0

        if not user or not user.check_password(password):
            if user:
                user.failed_attempts += 1
                if user.failed_attempts >= 5:
                    user.locked_until = now + timedelta(minutes=15)
                    user.is_locked = True
                db.session.add(
                    AuditLog(
                        user_id=user.id,
                        action="login_failed",
                        detail="Invalid credentials",
                        ip_address=AuditLog.hash_ip(request.remote_addr),
                    )
                )
                db.session.commit()

                ten_minutes_ago = now - timedelta(minutes=10)
                failures = AuditLog.query.filter(
                    AuditLog.user_id == user.id,
                    AuditLog.action == "login_failed",
                    AuditLog.created_at >= ten_minutes_ago,
                ).count()
                if failures >= 3:
                    db.session.add(
                        AnomalyAlert(
                            user_id=user.id,
                            rule_triggered="multiple_failed_logins",
                            detail="3+ failed logins within 10 minutes",
                            severity="high",
                        )
                    )
                    db.session.commit()

            flash("Invalid username or password.", "danger")
            logger.warning(
                "Failed login for user=%s ip=%s",
                username,
                AuditLog.hash_ip(request.remote_addr),
            )
            return render_template("auth/login.html", form=form), 401

        user.failed_attempts = 0
        user.is_locked = False
        user.locked_until = None
        db.session.add(
            AuditLog(
                user_id=user.id,
                action="login_success",
                detail="Login successful",
                ip_address=AuditLog.hash_ip(request.remote_addr),
            )
        )
        db.session.commit()
        logger.info("Login success user=%s", username)

        session_start = utcnow().isoformat()
        access_token = create_access_token(
            identity=user.id, additional_claims={"role": user.role}
        )
        refresh_token = create_refresh_token(
            identity=user.id, additional_claims={"session_start": session_start}
        )
        response = redirect(url_for("dashboard.index"))
        set_access_cookies(response, access_token)
        set_refresh_cookies(response, refresh_token)
        return response

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    response = redirect(url_for("auth.login"))
    unset_jwt_cookies(response)
    return response


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True, locations=["headers", "cookies"])
def refresh():
    identity = get_jwt_identity()
    claims = get_jwt()
    session_start_str = claims.get("session_start")
    if session_start_str:
        session_start = datetime.fromisoformat(session_start_str)
        if (utcnow() - session_start).total_seconds() > 28800:
            response = redirect(url_for("auth.login"))
            unset_jwt_cookies(response)
            return response
    else:
        session_start_str = utcnow().isoformat()

    access_token = create_access_token(identity=identity)
    refresh_token = create_refresh_token(
        identity=identity, additional_claims={"session_start": session_start_str}
    )
    response = redirect(url_for("dashboard.index"))
    set_access_cookies(response, access_token)
    set_refresh_cookies(response, refresh_token)
    return response


@auth_bp.route("/sign", methods=["POST"])
@limiter.limit("30/minute")
@jwt_required()
def sign_request():
    """Server-side HMAC signing proxy. The HMAC key never leaves the server."""
    identity = get_jwt_identity()
    user = User.query.get(identity)
    if not user:
        return "", 401
    data = request.get_json(silent=True) or {}
    method = data.get("method", "")
    path = data.get("path", "")
    body_string = data.get("body_string", "")
    body_hash = data.get("body_hash", "")

    timestamp = utcnow().isoformat() + "Z"
    nonce = secrets.token_hex(16)
    if isinstance(body_hash, str) and re.fullmatch(r"[0-9a-f]{64}", body_hash):
        normalized_body_hash = body_hash
    else:
        normalized_body_hash = hashlib.sha256(body_string.encode("utf-8")).hexdigest()
    payload = f"{method}{path}{timestamp}{normalized_body_hash}{nonce}".encode("utf-8")
    key = user.get_hmac_key()
    signature = hmac_mod.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return jsonify({"signature": signature, "timestamp": timestamp, "nonce": nonce})


@auth_bp.route("/change-password", methods=["GET", "POST"])
@jwt_required()
@hmac_required
def change_password():
    identity = get_jwt_identity()
    user = User.query.get(identity)
    if not user:
        return "", 401
    if request.method == "POST":
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")
        if not user.check_password(current_pw):
            flash("Current password is incorrect.", "danger")
            return render_template("auth/change_password.html"), 400
        if new_pw != confirm_pw:
            flash("New passwords do not match.", "danger")
            return render_template("auth/change_password.html"), 400
        if len(new_pw) < 12:
            flash("New password must be at least 12 characters.", "danger")
            return render_template("auth/change_password.html"), 400
        user.set_password(new_pw)
        db.session.commit()
        flash("Password changed successfully.", "success")
        return redirect(url_for("dashboard.index"))
    return render_template("auth/change_password.html")
