from datetime import datetime, timedelta

from app.extensions import db
from app.models import User
from conftest import hmac_headers, login_as


def test_login_200(client):
    response = client.post(
        "/auth/login",
        data={"username": "test_admin", "password": "TestPassword123!"},
        follow_redirects=True,
    )
    assert response.status_code == 200


def test_login_401(client):
    response = client.post(
        "/auth/login",
        data={"username": "test_admin", "password": "wrong"},
        follow_redirects=False,
    )
    assert response.status_code == 401


def test_locked_423(client, app):
    with app.app_context():
        user = User.query.filter_by(username="test_staff").first()
        user.locked_until = datetime.utcnow() + timedelta(minutes=5)
        user.is_locked = True
        db.session.commit()

    response = client.post(
        "/auth/login",
        data={"username": "test_staff", "password": "TestPassword123!"},
        follow_redirects=False,
    )
    assert response.status_code == 423


def test_no_token_401(client):
    response = client.get("/products/")
    assert response.status_code == 401


def test_login_sets_jwt_cookies(client):
    response = client.post(
        "/auth/login",
        data={"username": "test_admin", "password": "TestPassword123!"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert client.get_cookie("access_token_cookie") is not None
    assert client.get_cookie("refresh_token_cookie") is not None


def test_login_redirects_to_dashboard(client):
    response = client.post(
        "/auth/login",
        data={"username": "test_admin", "password": "TestPassword123!"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/dashboard" in response.location or response.location == "/"


def test_sign_endpoint_returns_signature_shape(client, app):
    login_as(client, "admin")
    response = client.post(
        "/auth/sign",
        json={"method": "POST", "path": "/products/", "body_string": "name=test"},
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "signature" in data
    assert "timestamp" in data
    assert "nonce" in data
    assert len(data["signature"]) == 64  # SHA-256 hex digest


def test_sign_endpoint_requires_auth(client):
    response = client.post(
        "/auth/sign",
        json={"method": "POST", "path": "/products/", "body_string": ""},
        content_type="application/json",
    )
    assert response.status_code == 401


def test_change_password_success(client, app):
    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
    data = {
        "current_password": "TestPassword123!",
        "new_password": "NewSecurePass456!",
        "confirm_password": "NewSecurePass456!",
    }
    headers = hmac_headers(staff, "POST", "/auth/change-password", data)
    response = client.post("/auth/change-password", data=data, headers=headers)
    assert response.status_code in (200, 302)


def test_change_password_wrong_current(client, app):
    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
    data = {
        "current_password": "WrongPassword!",
        "new_password": "NewSecurePass456!",
        "confirm_password": "NewSecurePass456!",
    }
    headers = hmac_headers(staff, "POST", "/auth/change-password", data)
    response = client.post("/auth/change-password", data=data, headers=headers)
    assert response.status_code == 400


def test_change_password_too_short(client, app):
    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
    data = {
        "current_password": "TestPassword123!",
        "new_password": "short",
        "confirm_password": "short",
    }
    headers = hmac_headers(staff, "POST", "/auth/change-password", data)
    response = client.post("/auth/change-password", data=data, headers=headers)
    assert response.status_code == 400


def test_logout_clears_cookies(client):
    login_as(client, "staff")
    client.post("/auth/logout")
    cookie = client.get_cookie("access_token_cookie")
    assert cookie is None or cookie.value in ("", None)
