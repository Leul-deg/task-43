from datetime import datetime, timedelta

from app.extensions import db
from app.models import User


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
