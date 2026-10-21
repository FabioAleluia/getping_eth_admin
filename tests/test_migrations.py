import sqlite3
from pathlib import Path
from unittest.mock import patch

from getping_admin.database.db import get_db
from getping_admin.database.migrate import init_db
from tests.support import IsolatedDatabaseTestCase


class LegacyMigrationTests(IsolatedDatabaseTestCase):
    def legacy_database(self, *, broken=False):
        path = Path(self.tempdir.name) / "legacy.db"
        with sqlite3.connect(path) as conn:
            conn.executescript("""
                CREATE TABLE admin_usuarios (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,nome TEXT NOT NULL,
                  username TEXT UNIQUE NOT NULL,email TEXT UNIQUE NOT NULL,senha_hash TEXT NOT NULL,
                  papel TEXT CHECK(papel IN ('superadmin','gestor')) NOT NULL,
                  ativo INTEGER NOT NULL DEFAULT 1,criado_em TEXT NOT NULL,ultimo_login TEXT);
                INSERT INTO admin_usuarios VALUES (1,'Original','original','original@example.com','original-hash','superadmin',1,'2026-01-01',NULL);
                CREATE TABLE legacy_reference(id INTEGER PRIMARY KEY,actor INTEGER REFERENCES admin_usuarios(id));
            """)
            conn.execute("INSERT INTO legacy_reference VALUES (1,?)", (999 if broken else 1,))
        self.app.config["DATABASE"] = str(path)
        return path

    def test_legacy_migration_preserves_user_and_references(self):
        self.legacy_database()
        init_db()
        init_db()
        with get_db() as conn:
            user = conn.execute("SELECT * FROM admin_usuarios WHERE id=1").fetchone()
            self.assertEqual(user["senha_hash"], "original-hash")
            self.assertEqual(user["trocar_senha"], 1)
            self.assertEqual(user["auth_version"], 0)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(conn.execute("SELECT actor FROM legacy_reference").fetchone()[0], 1)

    def test_invalid_legacy_references_roll_back_table_rebuild(self):
        self.legacy_database(broken=True)
        with self.assertRaises(RuntimeError):
            init_db()
        with get_db() as conn:
            user = conn.execute("SELECT * FROM admin_usuarios WHERE id=1").fetchone()
            self.assertEqual(user["senha_hash"], "original-hash")
            self.assertNotIn("auth_version", user.keys())
            self.assertIsNone(
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE name='admin_usuarios_new'"
                ).fetchone()
            )

    def test_versioned_migration_failure_rolls_back_version(self):
        # A SQL failure after a statement must not leave a partial migration marked applied.
        migrations = Path(self.tempdir.name) / "database/migrations"
        migrations.mkdir(parents=True)
        (migrations / "999_test.sql").write_text(
            "CREATE TABLE partial_migration(id INTEGER);\nINVALID SQL;\n"
        )
        with patch("getping_admin.database.migrate.MIGRATIONS_PATH", migrations):
            with self.assertRaises(sqlite3.OperationalError):
                init_db()
        with get_db() as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE name='partial_migration'"
                ).fetchone()
            )
            self.assertIsNone(
                conn.execute("SELECT version FROM schema_migrations WHERE version=999").fetchone()
            )
