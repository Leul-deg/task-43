from datetime import datetime

from app.extensions import db
from app.models import AnomalyAlert, AuditLog, User
from conftest import hmac_headers, login_as


# ── User Management ────────────────────────────────────────────────────────────

def test_non_admin_cannot_access_admin_routes(client):
    for role in ("staff", "content_editor", "inventory_manager", "trainer"):
        login_as(client, role)
        assert client.get("/admin/").status_code == 403
        assert client.get("/admin/users").status_code == 403
        assert client.get("/admin/audit-log").status_code == 403


def test_admin_can_list_users(client):
    login_as(client, "admin")
    resp = client.get("/admin/users")
    assert resp.status_code == 200
    assert b"test_staff" in resp.data


def test_admin_create_user_success(client, app):
    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    data = {"username": "new_user", "password": "SecurePass123!", "role": "staff"}
    headers = hmac_headers(admin, "POST", "/admin/users", data)
    resp = client.post("/admin/users", data=data, headers=headers, follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        user = User.query.filter_by(username="new_user").first()
        assert user is not None
        assert user.role == "staff"


def test_admin_create_user_short_password_rejected(client, app):
    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    data = {"username": "bad_user", "password": "short", "role": "staff"}
    headers = hmac_headers(admin, "POST", "/admin/users", data)
    resp = client.post("/admin/users", data=data, headers=headers, follow_redirects=False)
    assert resp.status_code == 302  # redirects back with flash error

    with app.app_context():
        assert User.query.filter_by(username="bad_user").first() is None


def test_admin_create_user_duplicate_username_rejected(client, app):
    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    data = {"username": "test_staff", "password": "SecurePass123!", "role": "staff"}
    headers = hmac_headers(admin, "POST", "/admin/users", data)
    resp = client.post("/admin/users", data=data, headers=headers, follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        count = User.query.filter_by(username="test_staff").count()
        assert count == 1  # no duplicate created


def test_admin_lock_and_unlock_user(client, app):
    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()
        staff = User.query.filter_by(username="test_staff").first()
        staff_id = staff.id

    lock_headers = hmac_headers(admin, "POST", f"/admin/users/{staff_id}/lock")
    resp = client.post(f"/admin/users/{staff_id}/lock", headers=lock_headers)
    assert resp.status_code == 302

    with app.app_context():
        staff = User.query.get(staff_id)
        assert staff.is_locked is True

    unlock_headers = hmac_headers(admin, "POST", f"/admin/users/{staff_id}/unlock")
    resp = client.post(f"/admin/users/{staff_id}/unlock", headers=unlock_headers)
    assert resp.status_code == 302

    with app.app_context():
        staff = User.query.get(staff_id)
        assert staff.is_locked is False
        assert staff.failed_attempts == 0


def test_lock_creates_audit_log_entry(client, app):
    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()
        staff = User.query.filter_by(username="test_staff").first()
        staff_id = staff.id

    headers = hmac_headers(admin, "POST", f"/admin/users/{staff_id}/lock")
    client.post(f"/admin/users/{staff_id}/lock", headers=headers)

    with app.app_context():
        log = AuditLog.query.filter_by(action="user_locked").first()
        assert log is not None
        assert str(staff_id) in log.detail


# ── Anomaly Dashboard ──────────────────────────────────────────────────────────

def test_admin_can_view_anomaly_dashboard(client, app):
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
        alert = AnomalyAlert(
            user_id=staff.id,
            rule_triggered="test_rule",
            detail="Test anomaly",
            severity="high",
        )
        db.session.add(alert)
        db.session.commit()

    login_as(client, "admin")
    resp = client.get("/admin/anomalies")
    assert resp.status_code == 200
    assert b"test_rule" in resp.data or b"Test anomaly" in resp.data


def test_admin_can_review_anomaly(client, app):
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
        alert = AnomalyAlert(
            user_id=staff.id,
            rule_triggered="review_rule",
            detail="Needs review",
            severity="medium",
        )
        db.session.add(alert)
        db.session.commit()
        alert_id = alert.id

    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    headers = hmac_headers(admin, "POST", f"/admin/anomalies/{alert_id}/review")
    resp = client.post(f"/admin/anomalies/{alert_id}/review", headers=headers)
    assert resp.status_code == 200

    with app.app_context():
        updated = AnomalyAlert.query.get(alert_id)
        assert updated.is_reviewed is True


def test_anomaly_dashboard_filter_by_reviewed(client, app):
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
        db.session.add(AnomalyAlert(
            user_id=staff.id, rule_triggered="r1",
            detail="OPEN_ALERT_DETAIL_UNIQUE", severity="low",
        ))
        reviewed = AnomalyAlert(
            user_id=staff.id, rule_triggered="r2",
            detail="CLOSED_ALERT_DETAIL_UNIQUE", severity="low",
        )
        reviewed.is_reviewed = True
        db.session.add(reviewed)
        db.session.commit()

    login_as(client, "admin")
    resp = client.get("/admin/anomalies?reviewed=false")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "OPEN_ALERT_DETAIL_UNIQUE" in html
    assert "CLOSED_ALERT_DETAIL_UNIQUE" not in html


# ── Audit Log ──────────────────────────────────────────────────────────────────

def test_admin_can_view_audit_log(client, app):
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
        db.session.add(AuditLog(
            user_id=staff.id, action="login_success",
            detail="Login successful", ip_address="hashed",
        ))
        db.session.commit()

    login_as(client, "admin")
    resp = client.get("/admin/audit-log")
    assert resp.status_code == 200
    assert b"login_success" in resp.data


def test_audit_log_filter_by_date_range(client, app):
    from datetime import timedelta

    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
        old_log = AuditLog(
            user_id=staff.id, action="old_action", detail="Old entry", ip_address="hashed",
        )
        old_log.created_at = datetime(2023, 1, 1)
        new_log = AuditLog(
            user_id=staff.id, action="new_action", detail="New entry", ip_address="hashed",
        )
        new_log.created_at = datetime(2025, 6, 1)
        db.session.add_all([old_log, new_log])
        db.session.commit()

    login_as(client, "admin")
    resp = client.get("/admin/audit-log?date_from=2025-01-01")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "new_action" in html
    assert "old_action" not in html


def test_audit_log_filter_by_action(client, app):
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
        db.session.add(AuditLog(
            user_id=staff.id, action="login_failed", detail="Invalid credentials",
            ip_address="hashed",
        ))
        db.session.add(AuditLog(
            user_id=staff.id, action="search", detail="Query: test",
            ip_address="hashed",
        ))
        db.session.commit()

    login_as(client, "admin")
    resp = client.get("/admin/audit-log?action=login_failed")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "login_failed" in html
    assert "search" not in html or "Query: test" not in html


def test_audit_log_invalid_date_returns_400(client):
    login_as(client, "admin")
    resp = client.get("/admin/audit-log?date_from=bad-date")
    assert resp.status_code == 400
