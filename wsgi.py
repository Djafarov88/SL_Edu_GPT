"""
WSGI entrypoint for production deployment.

Usage with Gunicorn:
    gunicorn -w 3 -b 127.0.0.1:8000 wsgi:application

The Flask app is served at / (root). Nginx is responsible for routing
requests from the public URL (e.g. https://example.com/academy/) to
this Gunicorn process.

See DEPLOY.md for the recommended Nginx configuration.
"""
import os
import logging
from werkzeug.middleware.proxy_fix import ProxyFix
from app import create_app
from extensions import db
from init_db import seed_if_empty, seed_positions_if_empty, run_startup_migrations

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

flask_app = create_app()

flask_app.wsgi_app = ProxyFix(
    flask_app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_prefix=1,
)

with flask_app.app_context():
    db.create_all()
    seed_if_empty()
    seed_positions_if_empty()
    run_startup_migrations()
    logger.info('[WSGI] Database initialised. Application ready.')

application = flask_app
app = flask_app
