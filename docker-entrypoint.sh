#!/usr/bin/env sh
# ---------------------------------------------------------------------------
# Container entrypoint: apply migrations, ensure admin, optionally seed,
# then exec the WSGI server. Safe to run on every deploy against a
# persistent database — migrations and seeding are both idempotent.
# ---------------------------------------------------------------------------
set -eu

echo "[entrypoint] Applying database migrations..."
# Alembic upgrade is idempotent: it only applies revisions newer than the
# database's current head. For a database that predates migrations (created
# via create_all, so it has the tables but no alembic_version), we adopt it by
# stamping the initial revision first, then upgrade. Safe on every deploy.
python - <<'PYCODE'
from app import create_app
from app.extensions import db
from flask_migrate import upgrade, stamp
from sqlalchemy import inspect

app = create_app()
with app.app_context():
    tables = set(inspect(db.engine).get_table_names())
    if "alembic_version" not in tables and "users" in tables:
        stamp(revision="head")
        print("[entrypoint] Adopted pre-migration schema (stamped head).")
    upgrade()
print("[entrypoint] Migrations applied.")
PYCODE

echo "[entrypoint] Ensuring root admin account..."
python - <<'PYCODE'
from app import create_app
from app.services.auth_service import ensure_root_admin
app = create_app()
with app.app_context():
    user = ensure_root_admin()
    print(f"[entrypoint] Root admin ready: {user.email}")
PYCODE

if [ "${SEED_ON_BOOT:-false}" = "true" ]; then
  echo "[entrypoint] Seeding initial dataset (only if empty)..."
  python - <<'PYCODE'
from app import create_app
from app.seed import run_seed
app = create_app()
with app.app_context():
    created = run_seed()
print("[entrypoint] Seed inserted." if created else "[entrypoint] Seed skipped (data already present).")
PYCODE
fi

echo "[entrypoint] Launching: $*"
exec "$@"
