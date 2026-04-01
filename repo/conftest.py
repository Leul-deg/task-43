import os
from datetime import datetime, timezone
import hashlib
import hmac
import uuid
from urllib.parse import urlencode

import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import User


@pytest.fixture(scope="function")
def app():
    os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing")
    os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-for-testing")
    os.environ.setdefault("HMAC_SECRET", "test-hmac-secret")
    os.environ.setdefault("ADMIN_PASSWORD", "SecureTestPass123!")
    app = create_app(config_class=TestConfig)
    with app.app_context():
        db.session.configure(expire_on_commit=False)
        db.create_all()
        users = [
            ("test_admin", "admin"),
            ("test_editor", "content_editor"),
            ("test_inventory", "inventory_manager"),
            ("test_trainer", "trainer"),
            ("test_staff", "staff"),
        ]
        for username, role in users:
            user = User(username=username, role=role)
            user.set_password("TestPassword123!")
            db.session.add(user)
        db.session.commit()
        yield app
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login_as(client, role):
    username_map = {
        "admin": "test_admin",
        "content_editor": "test_editor",
        "inventory_manager": "test_inventory",
        "trainer": "test_trainer",
        "staff": "test_staff",
    }
    username = username_map[role]
    response = client.post(
        "/auth/login",
        data={"username": username, "password": "TestPassword123!"},
        follow_redirects=False,
    )
    return response


def _body_string(data):
    items = []
    for key in sorted(data.keys()):
        value = data[key]
        if isinstance(value, list):
            for val in value:
                items.append((key, val))
        else:
            items.append((key, value))
    return urlencode(items, doseq=True)


def hmac_headers(user, method, path, data=None):
    data = data or {}
    body_string = _body_string(data)
    body_hash = hashlib.sha256(body_string.encode("utf-8")).hexdigest()
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    nonce = str(uuid.uuid4())
    payload = f"{method}{path}{timestamp}{body_hash}{nonce}".encode("utf-8")
    signature = hmac.new(user.get_hmac_key().encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return {
        "X-Signature": signature,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
    }
