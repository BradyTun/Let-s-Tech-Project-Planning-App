"""
wsgi.py
=======
Production WSGI entrypoint. Gunicorn loads `app` from this module:

    gunicorn --bind 0.0.0.0:8000 wsgi:app
"""

import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402

app = create_app(os.environ.get("APP_ENV", "production"))


if __name__ == "__main__":
    # Convenience for local `python wsgi.py` runs (development server).
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=app.debug)
