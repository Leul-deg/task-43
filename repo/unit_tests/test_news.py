import os
from datetime import datetime, timedelta

from app.extensions import db
from app.models import IngestionLog, NewsItem, NewsSource, QuarantinedFile
from app.news.ingest import ingest_news, _should_backoff, _record_log, _resolve_source


def test_rss_ingest_and_duplicate(app, tmp_path):
    watch = tmp_path / "watch"
    watch.mkdir()
    (watch / "processed").mkdir()
    app.config.update(WATCH_FOLDER=str(watch), QUARANTINE_FOLDER=str(tmp_path / "quarantine"))

    with app.app_context():
        source = NewsSource(name="RSS", source_type="rss", is_allowed=True, created_by=1)
        db.session.add(source)
        db.session.commit()

        rss_file = watch / "feed.rss"
        rss_file.write_text(
            """
            <rss><channel><item><title>Test News</title><description>Summary</description></item></channel></rss>
            """,
            encoding="utf-8",
        )
        ingest_news()
        assert NewsItem.query.count() == 1

        rss_file = watch / "feed.rss"
        rss_file.write_text(
            """
            <rss><channel><item><title>Test News</title><description>Summary</description></item></channel></rss>
            """,
            encoding="utf-8",
        )
        ingest_news()
        assert NewsItem.query.count() == 1


def test_malformed_quarantine_and_blocked_source(app, tmp_path):
    watch = tmp_path / "watch"
    watch.mkdir()
    (watch / "processed").mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    app.config.update(WATCH_FOLDER=str(watch), QUARANTINE_FOLDER=str(quarantine))

    with app.app_context():
        source = NewsSource(name="JSON", source_type="json", is_allowed=True, created_by=1)
        blocked = NewsSource(name="Blocked", source_type="html", is_allowed=False, created_by=1)
        db.session.add_all([source, blocked])
        db.session.commit()

        bad_file = watch / "bad.json"
        bad_file.write_text('{"items":[{"summary":"No title"}]}', encoding="utf-8")
        ingest_news()
        assert QuarantinedFile.query.count() == 1

        html_file = watch / "blocked.html"
        html_file.write_text("<html><title>Blocked</title></html>", encoding="utf-8")
        ingest_news()
        assert NewsItem.query.filter(NewsItem.title == "Blocked").count() == 0


def test_backoff_attempt_1_one_minute(app):
    with app.app_context():
        now = datetime.utcnow()
        _record_log("retry1.txt", "failed", "err", retries=1)
        IngestionLog.query.filter_by(filename="retry1.txt").first().completed_at = now - timedelta(seconds=30)
        db.session.commit()

        should_wait, retries = _should_backoff("retry1.txt")
        assert should_wait is True
        assert retries == 1


def test_backoff_attempt_1_past_window_proceeds(app):
    with app.app_context():
        now = datetime.utcnow()
        _record_log("retry1_pass.txt", "failed", "err", retries=1)
        IngestionLog.query.filter_by(filename="retry1_pass.txt").first().completed_at = now - timedelta(minutes=2)
        db.session.commit()

        should_wait, retries = _should_backoff("retry1_pass.txt")
        assert should_wait is False
        assert retries == 1


def test_backoff_attempt_2_five_minutes(app):
    with app.app_context():
        now = datetime.utcnow()
        _record_log("retry2.txt", "failed", "err", retries=2)
        IngestionLog.query.filter_by(filename="retry2.txt").first().completed_at = now - timedelta(minutes=2)
        db.session.commit()

        should_wait, retries = _should_backoff("retry2.txt")
        assert should_wait is True
        assert retries == 2


def test_backoff_attempt_2_past_window_proceeds(app):
    with app.app_context():
        now = datetime.utcnow()
        _record_log("retry2_pass.txt", "failed", "err", retries=2)
        IngestionLog.query.filter_by(filename="retry2_pass.txt").first().completed_at = now - timedelta(minutes=6)
        db.session.commit()

        should_wait, retries = _should_backoff("retry2_pass.txt")
        assert should_wait is False
        assert retries == 2


def test_backoff_attempt_3_fifteen_minutes(app):
    with app.app_context():
        now = datetime.utcnow()
        _record_log("retry3.txt", "failed", "err", retries=3)
        IngestionLog.query.filter_by(filename="retry3.txt").first().completed_at = now - timedelta(minutes=10)
        db.session.commit()

        should_wait, retries = _should_backoff("retry3.txt")
        assert should_wait is True
        assert retries == 3


def test_backoff_attempt_3_past_window_proceeds(app):
    with app.app_context():
        now = datetime.utcnow()
        _record_log("retry3_pass.txt", "failed", "err", retries=3)
        IngestionLog.query.filter_by(filename="retry3_pass.txt").first().completed_at = now - timedelta(minutes=16)
        db.session.commit()

        should_wait, retries = _should_backoff("retry3_pass.txt")
        assert should_wait is False
        assert retries == 3


def test_resolve_source_exact_prefix(app):
    """A source whose filename_prefix matches the file is returned."""
    with app.app_context():
        generic = NewsSource(name="Generic RSS", source_type="rss", is_allowed=True, created_by=1)
        espn = NewsSource(name="ESPN", source_type="rss", is_allowed=True,
                          filename_prefix="espn", created_by=1)
        db.session.add_all([generic, espn])
        db.session.commit()

        result = _resolve_source("espn_daily.rss", "rss")
        assert result.id == espn.id


def test_resolve_source_longest_prefix_wins(app):
    """When multiple prefixes match, the longest one wins."""
    with app.app_context():
        short = NewsSource(name="ESPN", source_type="rss", is_allowed=True,
                           filename_prefix="espn", created_by=1)
        long = NewsSource(name="ESPN NBA", source_type="rss", is_allowed=True,
                          filename_prefix="espn_nba", created_by=1)
        db.session.add_all([short, long])
        db.session.commit()

        result = _resolve_source("espn_nba_scores.rss", "rss")
        assert result.id == long.id


def test_resolve_source_fallback_to_generic(app):
    """When no prefix matches, the generic (no-prefix) source is used."""
    with app.app_context():
        generic = NewsSource(name="Generic RSS", source_type="rss", is_allowed=True, created_by=1)
        espn = NewsSource(name="ESPN", source_type="rss", is_allowed=True,
                          filename_prefix="espn", created_by=1)
        db.session.add_all([generic, espn])
        db.session.commit()

        result = _resolve_source("bbc_sport.rss", "rss")
        assert result.id == generic.id


def test_resolve_source_no_match_returns_none(app):
    """When no sources of the given type exist, None is returned."""
    with app.app_context():
        db.session.add(NewsSource(name="JSON Only", source_type="json",
                                  is_allowed=True, created_by=1))
        db.session.commit()

        result = _resolve_source("feed.rss", "rss")
        assert result is None
