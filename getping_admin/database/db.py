"""Conexões SQLite com commit, rollback e fechamento explícitos."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app


def database_path():
    return Path(current_app.config["DATABASE"]).resolve()


@contextmanager
def get_db():
    conn = sqlite3.connect(database_path(), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
