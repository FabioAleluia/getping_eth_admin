import sqlite3
import secrets
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "database" / "db_getping.db"
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"


@contextmanager
def get_db():
    """Gera conexão segura com timeout e WAL ativo."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA synchronous = NORMAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Inicializa tabelas a partir do schema e cria superadmin inicial se não existir."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())

        # Migração da tabela admin_usuarios para suportar novos papéis ('assistente') e coluna trocar_senha
        colunas_admin = [c["name"] for c in conn.execute("PRAGMA table_info(admin_usuarios)").fetchall()]
        if "trocar_senha" not in colunas_admin:
            conn.execute("ALTER TABLE admin_usuarios ADD COLUMN trocar_senha INTEGER NOT NULL DEFAULT 1")

        # Verifica se o schema da tabela admin_usuarios já possui 'assistente' no CHECK
        table_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='admin_usuarios'").fetchone()
        if table_sql and "'assistente'" not in table_sql["sql"]:
            # Recria a tabela preservando os dados com a nova CHECK constraint
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("""
                CREATE TABLE admin_usuarios_new (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome          TEXT NOT NULL,
                    username      TEXT NOT NULL UNIQUE,
                    email         TEXT NOT NULL UNIQUE,
                    senha_hash    TEXT NOT NULL,
                    papel         TEXT NOT NULL CHECK(papel IN ('superadmin', 'gestor', 'assistente')) DEFAULT 'assistente',
                    ativo         INTEGER NOT NULL DEFAULT 1,
                    trocar_senha  INTEGER NOT NULL DEFAULT 1,
                    criado_em     TEXT NOT NULL,
                    ultimo_login  TEXT
                )
            """)
            conn.execute("""
                INSERT INTO admin_usuarios_new (id, nome, username, email, senha_hash, papel, ativo, trocar_senha, criado_em, ultimo_login)
                SELECT id, nome, username, email, senha_hash, papel, ativo, trocar_senha, criado_em, ultimo_login
                FROM admin_usuarios
            """)
            conn.execute("DROP TABLE admin_usuarios")
            conn.execute("ALTER TABLE admin_usuarios_new RENAME TO admin_usuarios")
            conn.execute("PRAGMA foreign_keys = ON")

        # Garante que o usuário master 'administrator' existe
        agora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        user_admin = conn.execute("SELECT * FROM admin_usuarios WHERE username = 'administrator'").fetchone()

        if not user_admin:
            senha_hash = generate_password_hash("administrator")
            conn.execute(
                """
                INSERT INTO admin_usuarios (nome, username, email, senha_hash, papel, ativo, trocar_senha, criado_em)
                VALUES ('Administrador Master', 'administrator', 'administrator@getping.local', ?, 'superadmin', 1, 1, ?)
                """,
                (senha_hash, agora),
            )
            print("[DB] Usuário 'administrator' configurado com sucesso.")


def gerar_chave_licenca() -> str:
    """Gera uma chave formatada GPING-XXXX-XXXX-XXXX-XXXX"""
    partes = [secrets.token_hex(2).upper() for _ in range(4)]
    return f"GPING-{'-'.join(partes)}"
