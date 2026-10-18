import secrets
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from flask import current_app, g, has_request_context, request

BASE_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = BASE_DIR / 'database/schema.sql'


def database_path():
    return Path(current_app.config['DATABASE']).resolve()


@contextmanager
def get_db():
    conn = sqlite3.connect(database_path(), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA busy_timeout = 5000')
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Executado explicitamente via CLI; nunca cria credenciais automaticamente."""
    database_path().parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.execute('PRAGMA journal_mode = WAL')
        # Legacy migration runs before schema scripts and inside an explicit transaction.
        table = conn.execute("SELECT sql FROM sqlite_master WHERE name='admin_usuarios'").fetchone()
        if table and "'assistente'" not in table['sql']:
            columns = {r['name'] for r in conn.execute('PRAGMA table_info(admin_usuarios)')}
            conn.execute('PRAGMA foreign_keys = OFF')
            conn.execute('BEGIN IMMEDIATE')
            try:
                conn.execute("""CREATE TABLE admin_usuarios_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
                    username TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE,
                    senha_hash TEXT NOT NULL, papel TEXT NOT NULL
                    CHECK(papel IN ('superadmin','gestor','assistente')) DEFAULT 'assistente',
                    ativo INTEGER NOT NULL DEFAULT 1, trocar_senha INTEGER NOT NULL DEFAULT 1,
                    criado_em TEXT NOT NULL, ultimo_login TEXT)""")
                troca = 'trocar_senha' if 'trocar_senha' in columns else '1'
                conn.execute(f"""INSERT INTO admin_usuarios_new
                    SELECT id,nome,username,email,senha_hash,papel,ativo,{troca},criado_em,ultimo_login
                    FROM admin_usuarios""")
                conn.execute('DROP TABLE admin_usuarios')
                conn.execute('ALTER TABLE admin_usuarios_new RENAME TO admin_usuarios')
                if conn.execute('PRAGMA foreign_key_check').fetchone():
                    raise RuntimeError('Migração interrompida: referências inválidas no banco.')
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.execute('PRAGMA foreign_keys = ON')
        conn.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, aplicado_em TEXT NOT NULL)')
        conn.commit()
        conn.execute('BEGIN IMMEDIATE')
        columns = {r['name'] for r in conn.execute('PRAGMA table_info(admin_usuarios)')}
        for name, definition in [('trocar_senha', 'INTEGER NOT NULL DEFAULT 1'),
                                 ('auth_version', 'INTEGER NOT NULL DEFAULT 0')]:
            if name not in columns:
                conn.execute(f'ALTER TABLE admin_usuarios ADD COLUMN {name} {definition}')
        for migration in sorted((BASE_DIR / 'database/migrations').glob('*.sql')):
            version = int(migration.stem.split('_')[0])
            if not conn.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone():
                # complete_statement respects trigger bodies, unlike splitting on semicolons.
                statement = ''
                for line in migration.read_text(encoding='utf-8').splitlines(True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        conn.execute(statement)
                        statement = ''
                if statement.strip():
                    raise RuntimeError(f'Migração incompleta: {migration.name}')
                conn.execute("INSERT INTO schema_migrations VALUES (?, datetime('now'))", (version,))


def audit(conn, action, entity, entity_id, before=None, after=None):
    import json
    # Callers supply safe field sets, never full user rows or credentials.
    actor = g.user['id'] if has_request_context() and getattr(g, 'user', None) else None
    ip = request.remote_addr if has_request_context() else None
    conn.execute('''INSERT INTO admin_audit
        (actor_id,action,entity,entity_id,before_json,after_json,ip_origem,criado_em)
        VALUES (?,?,?,?,?,?,?,?)''',
        (actor, action, entity, str(entity_id), json.dumps(before, ensure_ascii=False),
         json.dumps(after, ensure_ascii=False), ip,
         datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')))


def gerar_chave_licenca():
    # Keep the legacy key shape unless the client has been verified for longer keys.
    size = 4 if current_app.config['EXTENDED_LICENSE_KEYS'] else 2
    return 'GPING-' + '-'.join(secrets.token_hex(size).upper() for _ in range(4))
