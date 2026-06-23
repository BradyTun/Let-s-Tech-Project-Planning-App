"""
app/__init__.py
===============
Application factory for the Let's Tech Club Operations Platform.

`create_app()` constructs a fully-wired Flask instance, binds the SQLAlchemy,
Flask-Migrate, and Flask-Mail extensions, registers the operations Blueprint,
and installs uniform JSON error handlers so the API never leaks stack traces.
"""

from __future__ import annotations

import os

from flask import Flask, jsonify, request

from config import get_config
from .extensions import db, migrate, mail


def create_app(config_name: str | None = None) -> Flask:
    """Construct and return a configured Flask application instance."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    config_class = get_config(config_name)
    app.config.from_object(config_class)
    config_class.init_app(app)

    # --- Bind extensions ----------------------------------------------
    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)

    # --- Register models so Alembic/migrate can discover metadata -----
    with app.app_context():
        from . import models  # noqa: F401

    # --- Blueprints ---------------------------------------------------
    from .auth import auth_bp
    from .routes import ops_bp
    from .portal import portal_bp
    from .api import api_v1_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(ops_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(api_v1_bp)

    _register_error_handlers(app)
    _register_cli(app)

    return app


def _register_error_handlers(app: Flask) -> None:
    """Uniform JSON error envelopes for the API surface."""

    @app.errorhandler(400)
    def _bad_request(err):
        return jsonify(ok=False, error="bad_request", message=str(err)), 400

    @app.errorhandler(404)
    def _not_found(err):
        return jsonify(ok=False, error="not_found", message="Resource not found."), 404

    @app.errorhandler(409)
    def _conflict(err):
        return jsonify(ok=False, error="conflict", message=str(err)), 409

    @app.errorhandler(422)
    def _unprocessable(err):
        return jsonify(ok=False, error="unprocessable", message=str(err)), 422

    @app.errorhandler(500)
    def _server_error(err):  # pragma: no cover - defensive
        app.logger.exception(
            "Unhandled server error on %s %s: %s",
            request.method,
            request.path,
            err,
        )
        return jsonify(ok=False, error="server_error",
                       message="An internal error occurred."), 500


def _register_cli(app: Flask) -> None:
    """Expose a `flask seed` command that loads the demo operations dataset."""

    @app.cli.command("seed")
    def seed():  # pragma: no cover - operational helper
        """Populate the database with the hackathon seed dataset."""
        from .seed import run_seed
        run_seed()
        print("Seed dataset loaded.")

    @app.cli.command("init-db")
    def init_db():  # pragma: no cover - operational helper
        """Create all tables directly (useful outside the migration flow)."""
        db.create_all()
        print("Database tables created.")

    @app.cli.command("ensure-admin")
    def ensure_admin():  # pragma: no cover - operational helper
        """Idempotently guarantee the configured root admin account exists."""
        from .services.auth_service import ensure_root_admin
        user = ensure_root_admin()
        print(f"Root admin ready: {user.email}")
