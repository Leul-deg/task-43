import os
from datetime import datetime, timedelta, timezone
import hashlib
import hmac

import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import Product, ProductVariant, User
from conftest import hmac_headers, login_as


def test_valid_hmac(client, app):
    login_as(client, "staff")
    with app.app_context():
        user = User.query.filter_by(username="test_staff").first()
    data = {"name": "Quick", "q": "term"}
    headers = hmac_headers(user, "POST", "/search/saved", {"name": "Quick"})
    response = client.post("/search/saved", data={"name": "Quick"}, headers=headers)
    assert response.status_code == 200


def test_invalid_hmac_rejected(client, app):
    login_as(client, "staff")
    headers = {"X-Signature": "bad", "X-Timestamp": datetime.now(timezone.utc).isoformat(), "X-Nonce": "abc"}
    response = client.post("/search/saved", data={"name": "Bad"}, headers=headers)
    assert response.status_code == 401


def test_timestamp_skew_rejected(client, app):
    login_as(client, "staff")
    with app.app_context():
        user = User.query.filter_by(username="test_staff").first()
    data = {"name": "Skew"}
    body_hash = hashlib.sha256("name=Skew".encode("utf-8")).hexdigest()
    timestamp = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    nonce = "skew-nonce"
    payload = f"POST/search/saved{timestamp}{body_hash}{nonce}".encode("utf-8")
    signature = hmac.new(user.hmac_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    headers = {"X-Signature": signature, "X-Timestamp": timestamp, "X-Nonce": nonce}
    response = client.post("/search/saved", data=data, headers=headers)
    assert response.status_code == 401


def test_nonce_replay_rejected(client, app):
    login_as(client, "staff")
    with app.app_context():
        user = User.query.filter_by(username="test_staff").first()
    headers = hmac_headers(user, "POST", "/search/saved", {"name": "Replay"})
    response = client.post("/search/saved", data={"name": "Replay"}, headers=headers)
    assert response.status_code == 200
    response = client.post("/search/saved", data={"name": "Replay"}, headers=headers)
    assert response.status_code == 401


def test_bleach_strips_script(client, app):
    login_as(client, "admin")
    with app.app_context():
        user = User.query.filter_by(username="test_admin").first()
    data = {
        "name": "Sanitize",
        "slug": "sanitize",
        "description": "<script>alert(1)</script><p>Ok</p>",
        "sku": "SAN-1",
        "base_price": "10",
    }
    headers = hmac_headers(user, "POST", "/products/", data)
    response = client.post("/products/", data=data, headers=headers)
    assert response.status_code == 302
    with app.app_context():
        product = Product.query.filter_by(slug="sanitize").first()
        assert "<script>" not in (product.description or "")


def test_idor_reservation_release(app, client):
    """Staff user B cannot release staff user A's reservation"""
    with app.app_context():
        from app.models import (
            User,
            ProductVariant,
            Product,
            Batch,
            Bin,
            Warehouse,
            Reservation,
            db,
        )
        from conftest import login_as
        from datetime import datetime, timedelta

        login_as(client, "admin")
        w = Warehouse(name="W_idor", location="X")
        db.session.add(w)
        db.session.flush()
        b = Bin(warehouse_id=w.id, label="B1")
        db.session.add(b)
        db.session.flush()
        p = Product(name="IDOR Test", slug="idor-test", is_published=True)
        db.session.add(p)
        db.session.flush()
        v = ProductVariant(product_id=p.id, sku="IDOR-SKU", base_price=10.0)
        db.session.add(v)
        db.session.flush()
        batch = Batch(variant_id=v.id, bin_id=b.id, quantity=100)
        db.session.add(batch)
        db.session.flush()
        user_a = User.query.filter_by(username="test_staff").first()
        r = Reservation(
            variant_id=v.id,
            user_id=user_a.id,
            quantity=1,
            status="held",
            expires_at=datetime.utcnow() + timedelta(minutes=20),
        )
        db.session.add(r)
        db.session.commit()
        reservation_id = r.id
        login_as(client, "trainer")
        resp = client.post(f"/inventory/reservations/{reservation_id}/release")
        assert resp.status_code in (403, 401)


def test_idor_saved_search_delete(app, client):
    """One user cannot delete another user's saved search"""
    with app.app_context():
        from app.models import SavedSearch, User, db
        from conftest import login_as

        user = User.query.filter_by(username="test_staff").first()
        s = SavedSearch(user_id=user.id, name="Private", query_params="{}", is_pinned=False)
        db.session.add(s)
        db.session.commit()
        saved_id = s.id
        login_as(client, "trainer")
        resp = client.delete(f"/search/saved/{saved_id}")
        assert resp.status_code in (403, 401)


def test_account_lockout_after_5_failures(app, client):
    """Account locks after 5 failed login attempts"""
    with app.app_context():
        for i in range(5):
            client.post("/auth/login", data={"username": "test_staff", "password": "wrongpass"})
        resp = client.post(
            "/auth/login", data={"username": "test_staff", "password": "TestPassword123!"}
        )
        assert resp.status_code == 423


def test_anomaly_created_on_failed_logins(app, client):
    """3+ failed logins create an anomaly alert"""
    with app.app_context():
        from app.models import AnomalyAlert, User, db

        user = User.query.filter_by(username="test_admin").first()
        AnomalyAlert.query.filter_by(user_id=user.id).delete()
        db.session.commit()
        for i in range(3):
            client.post("/auth/login", data={"username": "test_admin", "password": "wrongpass"})
        alert = AnomalyAlert.query.filter_by(
            user_id=user.id, rule_triggered="multiple_failed_logins"
        ).first()
        assert alert is not None
        assert alert.severity == "high"


def test_non_admin_cannot_manage_users(app, client):
    """Staff cannot access admin user management"""
    with app.app_context():
        from conftest import login_as

        login_as(client, "staff")
        resp = client.get("/admin/users")
        assert resp.status_code == 403


class TestCSRFEnforcement:
    """Verify CSRF is enforced on mutation endpoints when WTF_CSRF_ENABLED=True."""

    @pytest.fixture()
    def csrf_app(self):
        os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing")
        os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-for-testing")
        os.environ.setdefault("HMAC_SECRET", "test-hmac-secret")
        os.environ.setdefault("ADMIN_PASSWORD", "SecureTestPass123!")

        class CSRFConfig(TestConfig):
            WTF_CSRF_ENABLED = True
            JWT_COOKIE_CSRF_PROTECT = False

        app = create_app(config_class=CSRFConfig)
        with app.app_context():
            db.session.configure(expire_on_commit=False)
            db.create_all()
            user = User(username="csrf_user", role="staff")
            user.set_password("TestPassword123!")
            db.session.add(user)
            db.session.commit()
            yield app
            db.drop_all()

    @staticmethod
    def _extract_csrf(html: bytes) -> str:
        import re
        match = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', html)
        return match.group(1).decode() if match else ""

    def _login(self, client):
        page = client.get("/auth/login")
        token = self._extract_csrf(page.data)
        client.post(
            "/auth/login",
            data={"username": "csrf_user", "password": "TestPassword123!", "csrf_token": token},
            follow_redirects=False,
        )
        return token

    def test_sign_endpoint_rejects_without_csrf(self, csrf_app):
        """POST /auth/sign must be rejected without a CSRF token."""
        client = csrf_app.test_client()
        self._login(client)
        resp = client.post(
            "/auth/sign",
            json={"method": "POST", "path": "/test", "body_string": ""},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_sign_endpoint_accepts_with_csrf(self, csrf_app):
        """POST /auth/sign must succeed with a valid CSRF token."""
        client = csrf_app.test_client()
        token = self._login(client)
        resp = client.post(
            "/auth/sign",
            json={"method": "POST", "path": "/test", "body_string": ""},
            content_type="application/json",
            headers={"X-CSRFToken": token},
        )
        assert resp.status_code == 200
