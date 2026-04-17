import os
import secrets


def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).lower() in ("true", "1", "yes")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or secrets.token_hex(32)
    HMAC_SECRET = os.getenv("HMAC_SECRET") or secrets.token_hex(32)
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///data/sports_hub.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_ACCESS_TOKEN_EXPIRES = 1800
    JWT_REFRESH_TOKEN_EXPIRES = 28800
    JWT_TOKEN_LOCATION = ["headers", "cookies"]
    JWT_VERIFY_SUB = False
    # Forms + API: CSRF on by default (disable with WTF_CSRF_ENABLED=false for special tooling only).
    WTF_CSRF_ENABLED = _env_bool("WTF_CSRF_ENABLED", "true")
    # JWT cookies: align with Flask-JWT-Extended CSRF double-submit; Secure flag when behind HTTPS.
    JWT_COOKIE_CSRF_PROTECT = _env_bool("JWT_COOKIE_CSRF_PROTECT", "true")
    JWT_COOKIE_SECURE = _env_bool("JWT_COOKIE_SECURE", "false")
    _jwt_samesite = os.getenv("JWT_COOKIE_SAMESITE", "Lax").strip()
    JWT_COOKIE_SAMESITE = None if _jwt_samesite.lower() == "none" else _jwt_samesite
    RATELIMIT_DEFAULT = "60/minute"
    # Explicit storage avoids Flask-Limiter startup warning; use Redis in production if needed.
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "app/static/uploads")
    WATCH_FOLDER = os.getenv("WATCH_FOLDER", "watch_folder")
    QUARANTINE_FOLDER = os.getenv("QUARANTINE_FOLDER", "quarantine")
    OVERBOOKING_BUFFER = int(os.getenv("OVERBOOKING_BUFFER", "2"))
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "AdminPass12345!")


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    JWT_COOKIE_CSRF_PROTECT = False
    JWT_COOKIE_SECURE = False
    JWT_COOKIE_SAMESITE = None
    HMAC_SECRET = "test-hmac-secret"
