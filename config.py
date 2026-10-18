import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    DATABASE = os.environ.get('GETPING_DATABASE', str(BASE_DIR / 'database/db_getping.db'))
    ENVIRONMENT = os.environ.get('GETPING_ENV', 'production')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('GETPING_ENV', 'production') != 'development'
    SESSION_IDLE_SECONDS = 1800
    SESSION_ABSOLUTE_SECONDS = 86400
    PERMANENT_SESSION_LIFETIME = 86400
    MAX_CONTENT_LENGTH = 32 * 1024
    INIT_DB = False
    EXTENDED_LICENSE_KEYS = os.environ.get('GETPING_EXTENDED_KEYS', '0') == '1'
    REQUIRE_FINGERPRINT = os.environ.get('GETPING_REQUIRE_FINGERPRINT', '0') == '1'
    ALLOW_ASSISTANT_LICENSE_EDITS = False
    API_RATE_LIMIT = 120
    LOGIN_RATE_LIMIT = 10
    RATE_WINDOW_SECONDS = 60
    LOG_RETENTION_DAYS = 90
    CHECKIN_LOG_INTERVAL_SECONDS = 3600
    TRUSTED_PROXY_HOPS = int(os.environ.get('GETPING_PROXY_HOPS', '0'))
