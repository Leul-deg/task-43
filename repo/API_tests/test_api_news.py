from app.extensions import db
from app.models import NewsItem, NewsSource, QuarantinedFile, User
from conftest import hmac_headers, login_as


def test_get_list_and_detail(client, app):
    with app.app_context():
        source = NewsSource(name="API", source_type="rss", is_allowed=True, created_by=1)
        db.session.add(source)
        db.session.flush()
        item = NewsItem(source_id=source.id, title="News", summary="Sum", content="Body", file_hash="hash")
        db.session.add(item)
        db.session.commit()

    login_as(client, "staff")
    response = client.get("/news/")
    assert response.status_code == 200
    response = client.get(f"/news/{item.id}")
    assert response.status_code == 200


def test_sources_admin_only(client):
    login_as(client, "staff")
    response = client.get("/news/sources")
    assert response.status_code == 403

    login_as(client, "admin")
    response = client.get("/news/sources")
    assert response.status_code == 200


def test_admin_create_and_delete_source(client, app):
    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    data = {"name": "Test Feed", "source_type": "rss", "is_allowed": "on"}
    headers = hmac_headers(admin, "POST", "/news/sources", data)
    resp = client.post("/news/sources", data=data, headers=headers, follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        source = NewsSource.query.filter_by(name="Test Feed").first()
        assert source is not None
        assert source.is_allowed is True
        source_id = source.id

    headers = hmac_headers(admin, "DELETE", f"/news/sources/{source_id}")
    resp = client.delete(f"/news/sources/{source_id}", headers=headers)
    assert resp.status_code == 204

    with app.app_context():
        assert NewsSource.query.get(source_id) is None


def test_content_editor_can_update_news_item(client, app):
    with app.app_context():
        source = NewsSource(name="EditSrc", source_type="rss", is_allowed=True, created_by=1)
        db.session.add(source)
        db.session.flush()
        item = NewsItem(
            source_id=source.id, title="Original Title", summary="Sum",
            content="Body", file_hash="edit-hash",
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    login_as(client, "content_editor")
    with app.app_context():
        editor = User.query.filter_by(username="test_editor").first()

    data = {"title": "Updated Title", "summary": "New summary", "content": "New body"}
    headers = hmac_headers(editor, "PUT", f"/news/{item_id}", data)
    resp = client.put(f"/news/{item_id}", data=data, headers=headers)
    assert resp.status_code == 200

    with app.app_context():
        updated = NewsItem.query.get(item_id)
        assert updated.title == "Updated Title"


def test_staff_cannot_update_news_item(client, app):
    with app.app_context():
        source = NewsSource(name="GuardSrc", source_type="rss", is_allowed=True, created_by=1)
        db.session.add(source)
        db.session.flush()
        item = NewsItem(
            source_id=source.id, title="Guarded", summary="s",
            content="c", file_hash="guard-hash",
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()

    data = {"title": "Hijacked Title", "summary": "s", "content": "c"}
    headers = hmac_headers(staff, "PUT", f"/news/{item_id}", data)
    resp = client.put(f"/news/{item_id}", data=data, headers=headers)
    assert resp.status_code == 403


def test_admin_can_view_ingestion_logs(client):
    login_as(client, "admin")
    resp = client.get("/news/logs")
    assert resp.status_code == 200


def test_admin_can_view_quarantine(client):
    login_as(client, "admin")
    resp = client.get("/news/quarantine")
    assert resp.status_code == 200


def test_non_admin_cannot_view_logs(client):
    login_as(client, "staff")
    resp = client.get("/news/logs")
    assert resp.status_code == 403


def _make_quarantine_file(app, filename="bad.json", reason="parse error"):
    with app.app_context():
        qf = QuarantinedFile(filename=filename, reason=reason, file_hash=f"hash-{filename}")
        db.session.add(qf)
        db.session.commit()
        return qf.id


def test_admin_can_delete_quarantine_item(client, app):
    qf_id = _make_quarantine_file(app, "delete-me.json")

    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    headers = hmac_headers(admin, "DELETE", f"/news/quarantine/{qf_id}")
    resp = client.delete(f"/news/quarantine/{qf_id}", headers=headers)
    assert resp.status_code == 204

    with app.app_context():
        assert QuarantinedFile.query.get(qf_id) is None


def test_admin_can_release_quarantine_item(client, app):
    """Release moves file back to watch folder if it exists on disk; always deletes the DB record."""
    qf_id = _make_quarantine_file(app, "release-me.json")

    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    headers = hmac_headers(admin, "POST", f"/news/quarantine/{qf_id}/release")
    resp = client.post(f"/news/quarantine/{qf_id}/release", headers=headers,
                       follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        assert QuarantinedFile.query.get(qf_id) is None


def test_non_admin_cannot_delete_quarantine(client, app):
    qf_id = _make_quarantine_file(app, "protected.json")

    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()

    headers = hmac_headers(staff, "DELETE", f"/news/quarantine/{qf_id}")
    resp = client.delete(f"/news/quarantine/{qf_id}", headers=headers)
    assert resp.status_code == 403

    with app.app_context():
        assert QuarantinedFile.query.get(qf_id) is not None


def test_non_admin_cannot_release_quarantine(client, app):
    qf_id = _make_quarantine_file(app, "guard-release.json")

    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()

    headers = hmac_headers(staff, "POST", f"/news/quarantine/{qf_id}/release")
    resp = client.post(f"/news/quarantine/{qf_id}/release", headers=headers,
                       follow_redirects=False)
    assert resp.status_code == 403


def test_admin_can_update_source(client, app):
    with app.app_context():
        source = NewsSource(name="UpdatableSrc", source_type="rss", is_allowed=True, created_by=1)
        db.session.add(source)
        db.session.commit()
        source_id = source.id

    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    data = {"name": "RenamedSrc", "source_type": "json", "is_allowed": "on"}
    headers = hmac_headers(admin, "PUT", f"/news/sources/{source_id}", data)
    resp = client.put(f"/news/sources/{source_id}", data=data, headers=headers)
    assert resp.status_code == 200

    with app.app_context():
        updated = NewsSource.query.get(source_id)
        assert updated.name == "RenamedSrc"
        assert updated.source_type == "json"


def test_non_admin_cannot_update_source(client, app):
    with app.app_context():
        source = NewsSource(name="GuardedSrc", source_type="rss", is_allowed=True, created_by=1)
        db.session.add(source)
        db.session.commit()
        source_id = source.id

    login_as(client, "content_editor")
    with app.app_context():
        editor = User.query.filter_by(username="test_editor").first()

    data = {"name": "HijackedSrc", "source_type": "json"}
    headers = hmac_headers(editor, "PUT", f"/news/sources/{source_id}", data)
    resp = client.put(f"/news/sources/{source_id}", data=data, headers=headers)
    assert resp.status_code == 403


def test_news_list_invalid_date_returns_400(client):
    login_as(client, "staff")
    resp = client.get("/news/?date_from=not-a-date")
    assert resp.status_code == 400
