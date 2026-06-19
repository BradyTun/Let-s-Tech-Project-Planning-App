"""
app/extensions.py
=================
Singleton extension instances declared once and bound lazily inside the
application factory. Keeping them isolated here eliminates circular-import
hazards between models, services, and the factory itself.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail

db = SQLAlchemy()
migrate = Migrate()
mail = Mail()
