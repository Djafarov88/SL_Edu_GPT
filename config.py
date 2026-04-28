"""
Flask configuration classes for Sportleader Academy LMS.

Usage:
  FLASK_ENV=development  → DevelopmentConfig (SQLite allowed, insecure dev secret)
  FLASK_ENV=production   → ProductionConfig  (PostgreSQL required, strict validation)
  FLASK_ENV=testing      → TestingConfig
  (unset)                → ProductionConfig  (fail-safe default)

Production hard rules:
  - SESSION_SECRET must be set and ≥ 32 characters
  - DATABASE_URL must be set
  - DATABASE_URL must be a PostgreSQL URL (sqlite:// is BLOCKED)
  - Any violation raises RuntimeError and prevents startup
"""
import os
import logging
import sys

logger = logging.getLogger(__name__)


def _require_env(name, hint=''):
    val = os.environ.get(name, '').strip()
    if not val:
        msg = f'[CONFIG] {name} is required in production mode.'
        if hint:
            msg += f' {hint}'
        logger.critical(msg)
        raise RuntimeError(msg)
    return val


def _fix_db_url(url):
    if url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql://', 1)
    return url


class BaseConfig:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    TESTING = False
    SESSION_COOKIE_SECURE = False

    def __init__(self):
        raw_url = os.environ.get('DATABASE_URL', '').strip()
        if raw_url:
            url = _fix_db_url(raw_url)
            if url.startswith('sqlite'):
                raise RuntimeError(
                    '[CONFIG] Do not set DATABASE_URL to a SQLite path even in development. '
                    'Remove DATABASE_URL entirely to use the default SQLite fallback.'
                )
            logger.info(f'[CONFIG] Development mode using PostgreSQL at {url[:30]}...')
        else:
            base = os.path.dirname(os.path.abspath(__file__))
            url = f"sqlite:///{os.path.join(base, 'sportleader_dev.db')}"
            logger.warning(
                '[CONFIG] Development mode: using local SQLite database. '
                'Set DATABASE_URL for a PostgreSQL connection.'
            )

        secret = os.environ.get('SESSION_SECRET', '').strip()
        if not secret:
            secret = 'dev-insecure-secret-do-not-use-in-production'
            logger.warning('[CONFIG] SESSION_SECRET not set — using insecure dev fallback.')

        self.SQLALCHEMY_DATABASE_URI = url
        self.SECRET_KEY = secret


class ProductionConfig(BaseConfig):
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = 'https'

    def __init__(self):
        errors = []

        raw_url = os.environ.get('DATABASE_URL', '').strip()
        if not raw_url:
            errors.append(
                'DATABASE_URL is not set. '
                'PostgreSQL is required in production. '
                'Example: postgresql://user:pass@localhost:5432/sportleader_academy'
            )
            url = None
        else:
            url = _fix_db_url(raw_url)
            if url.startswith('sqlite'):
                errors.append(
                    'DATABASE_URL points to SQLite, which is NOT allowed in production. '
                    'Use a PostgreSQL URL.'
                )
                url = None

        secret = os.environ.get('SESSION_SECRET', '').strip()
        if not secret:
            errors.append(
                'SESSION_SECRET is not set. '
                'Generate one: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        elif len(secret) < 32:
            errors.append(
                f'SESSION_SECRET is too short ({len(secret)} chars). '
                'Must be at least 32 characters.'
            )

        if errors:
            for e in errors:
                logger.critical(f'[CONFIG] FATAL — {e}')
            print('\n' + '=' * 60, file=sys.stderr)
            print('STARTUP FAILED — production configuration errors:', file=sys.stderr)
            for e in errors:
                print(f'  • {e}', file=sys.stderr)
            print('=' * 60 + '\n', file=sys.stderr)
            raise RuntimeError(
                'Application cannot start. Fix the configuration errors above.'
            )

        self.SQLALCHEMY_DATABASE_URI = url
        self.SECRET_KEY = secret
        logger.info('[CONFIG] Production config loaded — PostgreSQL, secure cookies.')


class TestingConfig(BaseConfig):
    DEBUG = True
    TESTING = True
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = False

    def __init__(self):
        raw_url = os.environ.get('DATABASE_URL', '').strip()
        if raw_url:
            self.SQLALCHEMY_DATABASE_URI = _fix_db_url(raw_url)
        else:
            self.SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
        self.SECRET_KEY = os.environ.get('SESSION_SECRET', 'test-secret-key')


_CONFIGS = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
}


def get_config() -> dict:
    """
    Return a Flask config dict based on FLASK_ENV.
    Defaults to ProductionConfig when FLASK_ENV is not set.
    """
    env = os.environ.get('FLASK_ENV', 'production').lower().strip()
    config_class = _CONFIGS.get(env, ProductionConfig)
    logger.info(f'[CONFIG] FLASK_ENV={env!r} → {config_class.__name__}')
    instance = config_class()
    return {k: v for k, v in instance.__class__.__dict__.items()
            if not k.startswith('_') and k.isupper()} | \
           {k: v for k, v in instance.__dict__.items() if k.isupper()}
