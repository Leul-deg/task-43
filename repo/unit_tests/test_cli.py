import os
import tempfile

from app.extensions import db
from app.models import NewsItem, NewsSource, User


def test_ingest_news_cli(app):
    runner = app.test_cli_runner()
    with tempfile.TemporaryDirectory() as watch_dir:
        app.config["WATCH_FOLDER"] = watch_dir

        with app.app_context():
            admin = User.query.filter_by(role="admin").first()
            source = NewsSource(
                name="XML Feed", source_type="xml", is_allowed=True,
                created_by=admin.id,
            )
            db.session.add(source)
            db.session.commit()

        rss_content = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>CLI Test Article</title>
      <description>Testing ingest via CLI</description>
      <link>http://example.com/cli-test</link>
    </item>
  </channel>
</rss>"""
        rss_path = os.path.join(watch_dir, "feed.xml")
        with open(rss_path, "w") as f:
            f.write(rss_content)

        result = runner.invoke(args=["ingest-news"])
        assert result.exit_code == 0

        with app.app_context():
            article = NewsItem.query.filter_by(title="CLI Test Article").first()
            assert article is not None
            assert "Testing ingest via CLI" in (article.summary or "")
