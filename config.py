"""
config.py
=========
Centralized configuration architecture for the Let's Tech Club
"48 Hours to Survive in the AI Era" internal Operations Command Center.

Three discrete deployment surfaces are defined:

    * ProductionConfig  -> hardened, env-driven, no debug leakage.
    * DevelopmentConfig -> local iteration with verbose diagnostics.
    * TestingConfig     -> isolated, fast, suppresses real SMTP traffic.

Every externally-sensitive parameter is parsed cleanly from system
environment variables so that no secret is ever hard-coded into source.
"""

import os
from datetime import timedelta


def _env_bool(key: str, default: bool = False) -> bool:
    """Parse a boolean environment variable tolerantly."""
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_int(key: str, default: int) -> int:
    """Parse an integer environment variable with a safe fallback."""
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _normalize_db_url(url):
    """Coerce common managed-Postgres URL schemes to SQLAlchemy + psycopg2.

    Render/Heroku hand out `postgres://...`, which SQLAlchemy 2.x rejects.
    Normalize to `postgresql+psycopg2://...` so the app boots unchanged.
    """
    if not url:
        return url
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


class BaseConfig:
    """Shared baseline applied to every environment."""

    # --- Core security -------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")

    # --- SQLAlchemy ----------------------------------------------------
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,   # transparently recycle dead connections
        "pool_recycle": 280,
    }

    # --- Flask-Mail ----------------------------------------------------
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "localhost")
    MAIL_PORT = _env_int("MAIL_PORT", 587)
    MAIL_USE_TLS = _env_bool("MAIL_USE_TLS", True)
    MAIL_USE_SSL = _env_bool("MAIL_USE_SSL", False)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get(
        "MAIL_DEFAULT_SENDER", "ops@letstechclub.org"
    )
    MAIL_SUPPRESS_SEND = False

    # --- Session / cookie hardening ------------------------------------
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    JSON_SORT_KEYS = False

    # --- Authentication / OTP ------------------------------------------
    ROOT_ADMIN_EMAIL = os.environ.get(
        "ROOT_ADMIN_EMAIL", "kyawkokotunmm475157@gmail.com"
    ).strip().lower()
    OTP_TTL_MINUTES = _env_int("OTP_TTL_MINUTES", 10)
    OTP_MAX_ATTEMPTS = _env_int("OTP_MAX_ATTEMPTS", 5)
    OTP_LENGTH = _env_int("OTP_LENGTH", 6)
    # Public base URL used when composing invitation links in emails. On
    # Render this is supplied automatically via RENDER_EXTERNAL_URL, so the
    # app needs no manual configuration to build correct links.
    APP_BASE_URL = (
        os.environ.get("APP_BASE_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or "http://localhost:8000"
    )
    # When true (non-production), the OTP is also returned in the API response
    # and written to the server log so the app is usable without a live SMTP.
    OTP_DEV_ECHO = _env_bool("OTP_DEV_ECHO", True)

    @staticmethod
    def init_app(app):
        """Hook for environment-specific late initialization."""
        return None


class DevelopmentConfig(BaseConfig):
    """Local developer workstation profile."""

    DEBUG = True
    TESTING = False
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(os.path.abspath(os.path.dirname(__file__)), "ops_dev.db"),
    ))


class TestingConfig(BaseConfig):
    """Ephemeral CI / unit-test profile. Never touches a real SMTP relay."""

    DEBUG = False
    TESTING = True
    WTF_CSRF_ENABLED = False
    MAIL_SUPPRESS_SEND = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL", "sqlite:///:memory:"
    )


class ProductionConfig(BaseConfig):
    """Hardened, container-deployed profile."""

    DEBUG = False
    TESTING = False

    # Prefer an external DATABASE_URL (e.g. managed Postgres). When it is not
    # set, fall back to a persistent SQLite file under DATA_DIR so the app
    # boots without any external database. Mount a persistent disk at DATA_DIR
    # (e.g. a Render Disk) to keep the SQLite data across deploys/restarts.
    DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
    SQLALCHEMY_DATABASE_URI = (
        _normalize_db_url(os.environ.get("DATABASE_URL"))
        or "sqlite:///" + os.path.join(DATA_DIR, "app.db")
    )

    # Production refuses to silently boot on a throwaway secret.
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    OTP_DEV_ECHO = False

    @classmethod
    def init_app(cls, app):
        BaseConfig.init_app(app)
        uri = app.config.get("SQLALCHEMY_DATABASE_URI") or ""
        if not uri:
            raise RuntimeError(
                "No database configured: set DATABASE_URL or DATA_DIR."
            )
        # Ensure the SQLite directory exists when using the file fallback.
        if uri.startswith("sqlite:///"):
            db_path = uri[len("sqlite:///"):]
            directory = os.path.dirname(db_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
        weak_secrets = {"change-me-in-production", "please-change-me", "", None}
        if app.config.get("SECRET_KEY") in weak_secrets:
            raise RuntimeError(
                "A strong SECRET_KEY must be supplied for the production environment."
            )


config = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}


def get_config(name: str | None = None):
    """Resolve a config class from a name or the FLASK_ENV/APP_ENV variable."""
    key = (name or os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV") or "default")
    return config.get(key, config["default"])
