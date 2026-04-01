import logging
from datetime import datetime

import click
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import os

from flask import Flask, render_template
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from sqlalchemy import event

from .config import Config
from .extensions import csrf, db, jwt, limiter
from .models import Batch, Reservation, UsedNonce, User, utcnow


def create_app(config_class=None):
    load_dotenv()
    app = Flask(__name__)
    app.config.from_object(config_class or Config)
    required_secrets = {
        "SECRET_KEY": os.getenv("SECRET_KEY"),
        "JWT_SECRET_KEY": os.getenv("JWT_SECRET_KEY"),
        "HMAC_SECRET": os.getenv("HMAC_SECRET"),
    }
    placeholders = {
        "SECRET_KEY": "change-me-to-random-64-chars",
        "JWT_SECRET_KEY": "change-me-to-another-random-64-chars",
        "HMAC_SECRET": "change-me-hmac-secret",
    }
    default_admin = os.getenv("ADMIN_PASSWORD")
    missing = [name for name, value in required_secrets.items() if not value]
    if missing:
        raise RuntimeError(
            f"Missing required secrets in environment: {', '.join(missing)}"
        )
    weak = [name for name, value in required_secrets.items() if value == placeholders[name]]
    if weak:
        raise RuntimeError(
            f"Replace placeholder secrets before starting the app: {', '.join(weak)}"
        )
    if default_admin in (None, "AdminPass12345!"):
        raise RuntimeError("Set a custom ADMIN_PASSWORD before starting the app.")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.init_app(app)
    jwt.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    with app.app_context():
        if str(app.config.get("SQLALCHEMY_DATABASE_URI", "")).startswith("sqlite"):

            @event.listens_for(db.engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()

    from .admin.routes import admin_bp
    from .assessments.routes import assessments_bp
    from .auth.routes import auth_bp
    from .dashboard.routes import dashboard_bp
    from .inventory.routes import inventory_bp
    from .news.routes import news_bp
    from .pricing.routes import pricing_bp
    from .products.routes import products_bp
    from .search.routes import search_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(products_bp, url_prefix="/products")
    app.register_blueprint(inventory_bp, url_prefix="/inventory")
    app.register_blueprint(pricing_bp, url_prefix="/pricing")
    app.register_blueprint(search_bp, url_prefix="/search")
    app.register_blueprint(news_bp, url_prefix="/news")
    app.register_blueprint(assessments_bp, url_prefix="/assessments")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", error_code=400, error_message="Bad request."), 400

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", error_code=403, error_message="Forbidden."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", error_code=404, error_message="Page not found."), 404

    @app.errorhandler(429)
    def rate_limited(e):
        return render_template("error.html", error_code=429, error_message="Too many requests."), 429

    @app.errorhandler(500)
    def server_error(e):
        return render_template("error.html", error_code=500, error_message="Internal server error."), 500

    def seed_admin():
        existing_admin = User.query.filter_by(role="admin").first()
        if existing_admin:
            return
        admin = User(username="admin", role="admin")
        admin.set_password(app.config.get("ADMIN_PASSWORD"))
        db.session.add(admin)
        db.session.commit()

    @app.cli.command("db-init")
    def db_init():
        db.create_all()
        seed_admin()

    @app.cli.command("seed-admin")
    def seed_admin_command():
        seed_admin()

    @app.cli.command("cleanup-nonces")
    def cleanup_nonces_command():
        UsedNonce.cleanup_expired()

    @app.cli.command("rotate-hmac-keys")
    def rotate_hmac_keys():
        """Regenerate HMAC keys for all users. Users must re-login."""
        users = User.query.all()
        for u in users:
            u.set_hmac_key()
        db.session.commit()
        click.echo(f"Rotated HMAC keys for {len(users)} users.")

    def release_expired_holds():
        now = utcnow()
        expired = Reservation.query.filter(
            Reservation.status == "held", Reservation.expires_at < now
        ).all()
        for reservation in expired:
            reservation.status = "released"
        db.session.commit()

    @app.cli.command("release-expired-holds")
    def release_expired_holds_command():
        release_expired_holds()

    @app.cli.command("ingest-news")
    def ingest_news_command():
        from .news.ingest import ingest_news

        ingest_news()

    @app.context_processor
    def inject_user():
        try:
            verify_jwt_in_request(optional=True)
            identity = get_jwt_identity()
            user = User.query.get(identity) if identity else None
        except Exception:
            user = None
        return {"current_user": user}

    run_scheduler = os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug
    if app.config.get("TESTING"):
        run_scheduler = False

    if run_scheduler:
        scheduler = BackgroundScheduler(daemon=True)

        def release_expired_holds_job():
            with app.app_context():
                release_expired_holds()

        def cleanup_expired_nonces_job():
            with app.app_context():
                UsedNonce.cleanup_expired()

        scheduler.add_job(release_expired_holds_job, "interval", seconds=60)
        scheduler.add_job(cleanup_expired_nonces_job, "interval", hours=1)

        def ingest_news_job():
            with app.app_context():
                from .news.ingest import ingest_news

                ingest_news()

        scheduler.add_job(ingest_news_job, "interval", minutes=15)
        scheduler.start()
        logging.getLogger(__name__).info("Sports Hub app started, scheduler running")
        app.scheduler = scheduler

    return app
