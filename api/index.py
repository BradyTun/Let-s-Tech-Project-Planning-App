"""
api/index.py
============
Vercel serverless entrypoint for the Hackathon app.

Vercel's `@vercel/python` runtime imports this module and serves the exposed
WSGI ``app``. Because Vercel has no long-lived container to run the Docker
entrypoint, this module also performs a one-time, process-level database
bootstrap on cold start:

    * apply Alembic migrations (idempotent — only new revisions run),
    * adopt a pre-migration database by stamping head when needed,
    * seed the initial dataset / ensure the root admin (idempotent).

A Postgres advisory lock serializes the bootstrap so concurrent serverless
cold starts cannot race on schema changes. All of this means the only thing
you configure on Vercel is environment variables — attach Vercel Postgres and
deploy.
"""

from __future__ import annotations

import os
import sys

# Make the project root importable (api/ sits one level below the root).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402

# WSGI application object discovered and served by @vercel/python.
app = create_app(os.environ.get("APP_ENV", "production"))

# Arbitrary, app-specific constant used to serialize the migration/seed
# bootstrap across concurrent serverless cold starts via a Postgres advisory
# lock. Any process attempting the bootstrap waits until the holder releases.
_BOOTSTRAP_LOCK_KEY = 918273645
_BOOTSTRAPPED = False


def _run_bootstrap() -> None:
    """Apply migrations and seed once, serialized by a Postgres advisory lock."""
    from flask_migrate import upgrade, stamp
    from sqlalchemy import inspect, text

    from app.extensions import db

    with app.app_context():
        engine = db.engine
        is_postgres = engine.url.get_backend_name().startswith("postgresql")

        lock_conn = None
        if is_postgres:
            # Hold a session-level advisory lock on a dedicated connection for
            # the duration of the bootstrap so only one instance migrates.
            lock_conn = engine.connect()
            lock_conn.execute(
                text("SELECT pg_advisory_lock(:k)"), {"k": _BOOTSTRAP_LOCK_KEY}
            )
            lock_conn.commit()
        try:
            tables = set(inspect(engine).get_table_names())
            # Adopt a database created before migrations existed (tables but no
            # alembic_version) by stamping head before upgrading.
            if "alembic_version" not in tables and "users" in tables:
                stamp(revision="head")
            upgrade()

            if os.environ.get("SEED_ON_BOOT", "true").strip().lower() == "true":
                from app.seed import run_seed
                run_seed()
            else:
                from app.services.auth_service import ensure_root_admin
                ensure_root_admin()
        finally:
            if lock_conn is not None:
                lock_conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"),
                    {"k": _BOOTSTRAP_LOCK_KEY},
                )
                lock_conn.commit()
                lock_conn.close()


def _ensure_bootstrapped() -> None:
    """Run the bootstrap at most once per process; never block serving on it."""
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _BOOTSTRAPPED = True
    try:
        _run_bootstrap()
    except Exception as exc:  # pragma: no cover - serving must survive this
        app.logger.error("Database bootstrap failed: %s", exc)


# Perform the one-time bootstrap as the module is loaded on a cold start.
_ensure_bootstrapped()
