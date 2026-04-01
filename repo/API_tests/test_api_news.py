from app.extensions import db
from app.models import NewsItem, NewsSource, User
from conftest import login_as


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
