"""Inicialização e migrações explícitas do banco."""

import sqlite3
from contextlib import closing
from pathlib import Path

from getping_admin.database.db import database_path, get_db
from getping_admin.identity import invalid_identity_ids, normalize_identifier

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
MIGRATIONS_PATH = Path(__file__).with_name("migrations")


def supports_assistant(table_sql):
    """Check the actual constraint in an isolated database, independent of SQL quoting."""
    with closing(sqlite3.connect(":memory:")) as probe:
        probe.execute(table_sql)
        try:
            probe.execute("""INSERT INTO admin_usuarios
                (nome,username,email,senha_hash,papel,ativo,criado_em)
                VALUES ('probe','probe','probe@example.invalid','probe','superadmin',1,'2000-01-01')""")
        except sqlite3.DatabaseError as error:
            raise RuntimeError("Schema de usuários desconhecido; revise a migração.") from error
        try:
            probe.execute("UPDATE admin_usuarios SET papel='assistente'")
        except sqlite3.IntegrityError as error:
            if "CHECK constraint failed" in str(error):
                return False
            raise RuntimeError("Schema de usuários desconhecido; revise a migração.") from error
    return True


def init_db():
    """Executado explicitamente via CLI; nunca cria credenciais automaticamente."""
    database_path().parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        # Legacy migration runs before schema scripts and inside an explicit transaction.
        table = conn.execute("SELECT sql FROM sqlite_master WHERE name='admin_usuarios'").fetchone()
        if table and not supports_assistant(table["sql"]):
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(admin_usuarios)")}
            known = {
                "id",
                "nome",
                "username",
                "email",
                "senha_hash",
                "papel",
                "ativo",
                "trocar_senha",
                "criado_em",
                "ultimo_login",
                "auth_version",
            }
            if columns - known:
                raise RuntimeError("Colunas de usuários desconhecidas; migração manual necessária.")
            objects = conn.execute(
                "SELECT sql FROM sqlite_master WHERE tbl_name='admin_usuarios' AND type IN ('index','trigger') AND sql IS NOT NULL"
            ).fetchall()
            sequence = None
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
                sequence = conn.execute(
                    "SELECT seq FROM sqlite_sequence WHERE name='admin_usuarios'"
                ).fetchone()
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("""CREATE TABLE admin_usuarios_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
                    username TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE,
                    senha_hash TEXT NOT NULL, papel TEXT NOT NULL
                    CHECK(papel IN ('superadmin','gestor','assistente')) DEFAULT 'assistente',
                    ativo INTEGER NOT NULL DEFAULT 1, trocar_senha INTEGER NOT NULL DEFAULT 1,
                    criado_em TEXT NOT NULL, ultimo_login TEXT,
                    auth_version INTEGER NOT NULL DEFAULT 0)""")
                troca = "trocar_senha" if "trocar_senha" in columns else "1"
                generation = "auth_version" if "auth_version" in columns else "0"
                conn.execute(f"""INSERT INTO admin_usuarios_new
                    SELECT id,nome,username,email,senha_hash,papel,ativo,{troca},criado_em,ultimo_login,{generation}
                    FROM admin_usuarios""")
                conn.execute("DROP TABLE admin_usuarios")
                conn.execute("ALTER TABLE admin_usuarios_new RENAME TO admin_usuarios")
                for obj in objects:
                    conn.execute(obj["sql"])
                if sequence:
                    conn.execute(
                        "UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name='admin_usuarios'",
                        (sequence[0],),
                    )
                if conn.execute("PRAGMA foreign_key_check").fetchone():
                    raise RuntimeError("Migração interrompida: referências inválidas no banco.")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, aplicado_em TEXT NOT NULL)"
        )
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(admin_usuarios)")}
        for name, definition in [
            ("trocar_senha", "INTEGER NOT NULL DEFAULT 1"),
            ("auth_version", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            if name not in columns:
                conn.execute(f"ALTER TABLE admin_usuarios ADD COLUMN {name} {definition}")
        for migration in sorted(MIGRATIONS_PATH.glob("*.sql")):
            version = int(migration.stem.split("_")[0])
            if not conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version=?", (version,)
            ).fetchone():
                if version == 3:
                    invalid = invalid_identity_ids(conn)
                    if invalid:
                        raise RuntimeError(
                            f"Identificadores de autenticação vazios ou conflitantes (IDs): {invalid}. "
                            "Revise as contas antes de aplicar a migração 003."
                        )
                    for row in conn.execute(
                        "SELECT id,username,email FROM admin_usuarios"
                    ).fetchall():
                        username = normalize_identifier(row["username"])
                        email = normalize_identifier(row["email"])
                        if (username, email) == (row["username"], row["email"]):
                            continue
                        conn.execute(
                            "UPDATE admin_usuarios SET username=?,email=? WHERE id=?",
                            (username, email, row["id"]),
                        )
                # complete_statement respects trigger bodies, unlike splitting on semicolons.
                statement = ""
                for line in migration.read_text(encoding="utf-8").splitlines(True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        conn.execute(statement)
                        statement = ""
                if statement.strip():
                    raise RuntimeError(f"Migração incompleta: {migration.name}")
                conn.execute(
                    "INSERT INTO schema_migrations VALUES (?, datetime('now'))", (version,)
                )
