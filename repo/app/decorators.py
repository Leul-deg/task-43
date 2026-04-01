import logging
from functools import wraps
from datetime import datetime, timezone
import hashlib
import hmac
from urllib.parse import urlencode

from flask import abort, current_app, request
from flask_jwt_extended import get_jwt_identity

from .extensions import db
from .models import UsedNonce, User, utcnow

logger = logging.getLogger(__name__)


def role_required(*allowed_roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            identity = get_jwt_identity()
            if not identity:
                return abort(403)
            user = User.query.get(identity)
            if not user or user.role not in allowed_roles:
                return abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def hmac_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if request.method not in {"POST", "PUT", "DELETE"}:
            return fn(*args, **kwargs)
        signature = request.headers.get("X-Signature")
        timestamp = request.headers.get("X-Timestamp")
        nonce = request.headers.get("X-Nonce")
        if not signature or not timestamp or not nonce:
            logger.warning("HMAC rejected: missing headers")
            return "", 401

        try:
            normalized = timestamp.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            now = utcnow()
            parsed_utc_naive = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            logger.warning("HMAC rejected: timestamp skew")
            return "", 401

        if abs((now - parsed_utc_naive).total_seconds()) > 300:
            logger.warning("HMAC rejected: timestamp skew")
            return "", 401

        if UsedNonce.is_replay(nonce):
            logger.warning("HMAC rejected: nonce replay")
            return "", 401

        if request.mimetype in {"multipart/form-data", "application/x-www-form-urlencoded"}:
            form_items = []
            for key in sorted(request.form.keys()):
                values = request.form.getlist(key)
                for value in values:
                    form_items.append((key, value))
            body_string = urlencode(form_items, doseq=True)
            body_hash = hashlib.sha256(body_string.encode("utf-8")).hexdigest()
        else:
            body = request.get_data(cache=True) or b""
            body_hash = hashlib.sha256(body).hexdigest()
        payload = f"{request.method}{request.path}{timestamp}{body_hash}{nonce}".encode("utf-8")

        identity = get_jwt_identity()
        user = User.query.get(identity) if identity else None
        key = user.get_hmac_key() if user and user.hmac_key else current_app.config.get("HMAC_SECRET", "")
        expected = hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected, signature):
            logger.warning("HMAC rejected: signature mismatch")
            return "", 401

        db.session.add(UsedNonce(nonce=nonce))
        db.session.commit()
        return fn(*args, **kwargs)

    return wrapper
