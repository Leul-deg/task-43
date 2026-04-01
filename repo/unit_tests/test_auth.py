from datetime import datetime, timedelta

from flask_jwt_extended import create_refresh_token

from app.extensions import db
from app.models import User, utcnow
from conftest import login_as


def test_login_success(client):
    response = client.post(
        "/auth/login",
        data={"username": "test_admin", "password": "TestPassword123!"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_login_wrong_password(client):
    response = client.post(
        "/auth/login",
        data={"username": "test_admin", "password": "wrong"},
        follow_redirects=False,
    )
    assert response.status_code == 401


def test_lockout_after_failed_attempts(client, app):
    for _ in range(5):
        client.post(
            "/auth/login",
            data={"username": "test_staff", "password": "wrong"},
            follow_redirects=False,
        )
    response = client.post(
        "/auth/login",
        data={"username": "test_staff", "password": "TestPassword123!"},
        follow_redirects=False,
    )
    assert response.status_code == 423


def test_lockout_expiry(client, app):
    with app.app_context():
        user = User.query.filter_by(username="test_staff").first()
        user.locked_until = datetime.utcnow() - timedelta(minutes=1)
        user.is_locked = True
        db.session.commit()

    response = client.post(
        "/auth/login",
        data={"username": "test_staff", "password": "TestPassword123!"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_role_required_blocks_wrong_role(client):
    login_as(client, "staff")
    response = client.get("/admin/")
    assert response.status_code == 403


def test_role_required_allows_correct_role(client):
    login_as(client, "admin")
    response = client.get("/admin/")
    assert response.status_code == 200


def test_hmac_key_not_in_cookies(client, app):
    """HMAC key must never be exposed in browser cookies (server-side signing)."""
    resp = client.post(
        "/auth/login",
        data={"username": "test_staff", "password": "TestPassword123!"},
        follow_redirects=False,
    )
    cookies = resp.headers.get_all("Set-Cookie")
    hmac_cookie = next((c for c in cookies if c.startswith("_hmac_key=")), "")
    assert not hmac_cookie, "HMAC key should not be in a cookie"


def test_sign_endpoint(client, app):
    """Server-side /auth/sign returns valid HMAC headers."""
    login_as(client, "staff")
    resp = client.post(
        "/auth/sign",
        json={"method": "POST", "path": "/products/create", "body_string": "name=Test"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "signature" in data
    assert "timestamp" in data
    assert "nonce" in data


def test_cookie_refresh_lifecycle(client, app):
    login_resp = client.post(
        "/auth/login",
        data={"username": "test_admin", "password": "TestPassword123!"},
        follow_redirects=False,
    )
    assert login_resp.status_code == 302
    login_cookies = login_resp.headers.get_all("Set-Cookie")
    assert any(cookie.startswith("refresh_token_cookie=") for cookie in login_cookies)

    refresh_resp = client.post(
        "/auth/refresh",
        headers={},
        follow_redirects=False,
    )
    assert refresh_resp.status_code == 302
    refresh_cookies = refresh_resp.headers.get_all("Set-Cookie")
    assert any(cookie.startswith("access_token_cookie=") for cookie in refresh_cookies)
    assert any(cookie.startswith("refresh_token_cookie=") for cookie in refresh_cookies)


def test_auth_failure_logs_no_raw_ip(client, app, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        client.post(
            "/auth/login",
            data={"username": "test_admin", "password": "wrong"},
            follow_redirects=False,
        )

    import re
    ip_pattern = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
    for record in caplog.records:
        assert not ip_pattern.search(record.message), f"Raw IP leaked in log: {record.message}"


def test_refresh_rejected_after_8_hours(client, app):
    """Refresh must be rejected once the absolute 8-hour session ceiling is exceeded."""
    login_as(client, "admin")

    with app.app_context():
        user = User.query.filter_by(username="test_admin").first()
        expired_start = (utcnow() - timedelta(hours=9)).isoformat()
        old_refresh = create_refresh_token(
            identity=user.id,
            additional_claims={"session_start": expired_start},
        )

    client.set_cookie("refresh_token_cookie", old_refresh, domain="localhost")
    resp = client.post("/auth/refresh", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers.get("Location", "")


def test_refresh_allowed_within_8_hours(client, app):
    """Refresh must succeed when within the 8-hour session window."""
    login_as(client, "admin")
    resp = client.post("/auth/refresh", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" not in resp.headers.get("Location", "")
