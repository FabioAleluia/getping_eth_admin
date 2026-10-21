"""Configuração lida a cada criação da aplicação, com overrides explícitos."""

import os
from pathlib import Path


def load_config(instance_path, overrides=None):
    environment = os.environ.get("GETPING_ENV", "production")
    # Preserve existing source installations without moving operational data.
    legacy_database = Path(__file__).resolve().parent.parent / "database/db_getping.db"
    default_database = (
        legacy_database if legacy_database.is_file() else Path(instance_path) / "db_getping.db"
    )
    config = {
        "SECRET_KEY": os.environ.get("SECRET_KEY"),
        "DATABASE": os.environ.get("GETPING_DATABASE", str(default_database)),
        "ENVIRONMENT": environment,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_IDLE_SECONDS": 1800,
        "SESSION_ABSOLUTE_SECONDS": 86400,
        "PERMANENT_SESSION_LIFETIME": 86400,
        "MAX_CONTENT_LENGTH": 32 * 1024,
        "INIT_DB": False,
        "REQUIRE_HTTPS": os.environ.get("GETPING_REQUIRE_HTTPS", "0") == "1",
        "PUBLIC_BASE_URL": os.environ.get("GETPING_PUBLIC_BASE_URL", ""),
        "EXTENDED_LICENSE_KEYS": os.environ.get("GETPING_EXTENDED_KEYS", "0") == "1",
        "REQUIRE_FINGERPRINT": os.environ.get("GETPING_REQUIRE_FINGERPRINT", "0") == "1",
        "ALLOW_ASSISTANT_LICENSE_EDITS": False,
        "API_RATE_LIMIT": 120,
        "LOGIN_RATE_LIMIT": 10,
        "RATE_WINDOW_SECONDS": 60,
        "LOG_RETENTION_DAYS": 90,
        "CHECKIN_LOG_INTERVAL_SECONDS": 3600,
        "TRUSTED_PROXY_HOPS": os.environ.get("GETPING_PROXY_HOPS", "0"),
    }
    overrides = dict(overrides or {})
    config.update(overrides)
    if "SESSION_COOKIE_SECURE" not in overrides:
        config["SESSION_COOKIE_SECURE"] = config["ENVIRONMENT"] != "development"
    hops = config["TRUSTED_PROXY_HOPS"]
    if isinstance(hops, bool) or not isinstance(hops, (int, str)):
        raise RuntimeError("GETPING_PROXY_HOPS deve ser um número inteiro não negativo.")
    try:
        hops = int(hops)
    except ValueError as error:
        raise RuntimeError("GETPING_PROXY_HOPS deve ser um número inteiro não negativo.") from error
    if hops < 0:
        raise RuntimeError("GETPING_PROXY_HOPS deve ser um número inteiro não negativo.")
    config["TRUSTED_PROXY_HOPS"] = hops
    return config
