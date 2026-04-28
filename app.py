import os
import logging
from flask import Flask, render_template, request
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple
from extensions import db, login_manager, csrf, limiter
from config import get_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__)
    app.config.update(get_config())

    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Войдите в систему для доступа к порталу'
    login_manager.login_message_category = 'warning'

    from models import User

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    from routes.auth import auth_bp
    from routes.main import main_bp
    from routes.learn import learn_bp
    from routes.admin import admin_bp
    from routes.chat import chat_bp
    from routes.content import content_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(learn_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(content_bp)

    import json as _json

    @app.template_filter('from_json')
    def from_json_filter(s):
        try:
            return _json.loads(s)
        except Exception:
            return []

    @app.template_filter('enumerate')
    def enumerate_filter(iterable):
        return enumerate(iterable)

    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        if not app.debug:
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net cdn.quilljs.com; "
                "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net cdn.quilljs.com fonts.googleapis.com; "
                "font-src 'self' fonts.gstatic.com cdn.jsdelivr.net; "
                "img-src 'self' data:; "
                "connect-src 'self';"
            )
        return response

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        logger.error(f'Internal server error: {e}', exc_info=True)
        return render_template('errors/500.html'), 500

    @app.errorhandler(429)
    def rate_limited(e):
        return render_template('errors/429.html'), 429

    return app


def create_wsgi_app():
    from flask import Flask as _Flask
    app = create_app()
    dummy = _Flask('dummy')

    @dummy.route('/')
    def root():
        from flask import redirect
        return redirect('/academy/')

    wsgi_app = DispatcherMiddleware(dummy, {'/academy': app})
    return wsgi_app, app


if __name__ == '__main__':
    wsgi_app, flask_app = create_wsgi_app()
    with flask_app.app_context():
        db.create_all()
        from init_db import seed_if_empty, seed_positions_if_empty, run_startup_migrations
        seed_if_empty()
        seed_positions_if_empty()
        run_startup_migrations()
    port = int(os.environ.get('PORT', 5000))
    run_simple('0.0.0.0', port, wsgi_app, use_reloader=False, use_debugger=False)
