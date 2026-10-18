from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
import click
from werkzeug.security import generate_password_hash
from database.db import init_db, get_db, database_path, audit
from core.security import validar_complexidade_senha


def register_commands(app):
    @app.cli.command('init-db')
    def initialize():
        """Aplica schema e migrações; preserve backup antes de atualizar."""
        init_db()
        click.echo('Schema e migrações aplicados. Nenhuma senha foi criada ou alterada.')

    @app.cli.command('create-admin')
    @click.option('--email', prompt=True)
    @click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(email, password):
        """Provisiona o administrador inicial apenas quando ainda não há superadmin."""
        valid, message = validar_complexidade_senha(password)
        if not valid:
            raise click.ClickException(message)
        if '@' not in email or len(email) > 254:
            raise click.ClickException('E-mail inválido.')
        with get_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute("SELECT 1 FROM admin_usuarios WHERE papel='superadmin'").fetchone():
                raise click.ClickException('Já existe superadmin. Use o painel para administrar contas.')
            cursor = conn.execute('''INSERT INTO admin_usuarios
                (nome,username,email,senha_hash,papel,ativo,trocar_senha,criado_em)
                VALUES ('Administrador Master','administrator',?,?,'superadmin',1,1,?)''',
                (email.strip().lower(), generate_password_hash(password),
                 datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')))
            audit(conn, 'create', 'usuario', cursor.lastrowid, after={'papel':'superadmin'})
        click.echo('Administrador criado. Troca de senha exigida no primeiro acesso.')

    @app.cli.command('reset-password')
    @click.argument('username')
    @click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
    def reset_password(username, password):
        """Recuperação local: redefine senha, revoga sessões e reativa a conta."""
        valid, message = validar_complexidade_senha(password)
        if not valid:
            raise click.ClickException(message)
        with get_db() as conn:
            user = conn.execute('SELECT id FROM admin_usuarios WHERE username=?', (username,)).fetchone()
            if not user:
                raise click.ClickException('Usuário não encontrado.')
            conn.execute('UPDATE admin_usuarios SET senha_hash=?, auth_version=auth_version+1, ativo=1, trocar_senha=1 WHERE id=?',
                         (generate_password_hash(password), user['id']))
            audit(conn, 'local_password_reset', 'usuario', user['id'])
        click.echo('Senha redefinida. Sessões revogadas; troca obrigatória no próximo acesso.')

    @app.cli.command('backup-db')
    @click.argument('destination', type=click.Path(path_type=Path))
    def backup(destination):
        """Backup SQLite consistente incluindo WAL; não sobrescreve arquivos."""
        if destination.resolve() == database_path():
            raise click.ClickException('Destino deve ser diferente do banco original.')
        try:
            with destination.open('xb'):
                pass
        except FileExistsError:
            raise click.ClickException('Destino já existe.')
        try:
            destination.chmod(0o600)
            with get_db() as source, sqlite3.connect(destination) as target:
                source.backup(target)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        click.echo('Backup concluído.')

    @app.cli.command('prune-logs')
    def prune():
        """Remove logs de validação antigos; preserva auditoria administrativa."""
        days = app.config['LOG_RETENTION_DAYS']
        if not isinstance(days, int) or days < 1:
            raise click.ClickException('LOG_RETENTION_DAYS precisa ser positivo.')
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        with get_db() as conn:
            count = conn.execute('DELETE FROM licenca_logs WHERE criado_em < ?', (cutoff,)).rowcount
            import time
            window = int(time.time()) // app.config["RATE_WINDOW_SECONDS"]
            conn.execute("DELETE FROM request_limits WHERE window < ?", (window - 1,))
        click.echo(f'{count} logs antigos removidos. Auditoria administrativa preservada.')

    @app.cli.command('check-data')
    def check_data():
        """Relata IDs de licenças legadas inválidas sem alterá-las."""
        with get_db() as conn:
            rows = conn.execute('SELECT id, limite_hosts,limite_agentes,data_expiracao FROM licencas').fetchall()
        invalid = []
        for row in rows:
            try:
                datetime.strptime(row['data_expiracao'], '%Y-%m-%d %H:%M:%S')
                if not 1 <= row['limite_hosts'] <= 10000 or not 0 <= row['limite_agentes'] <= 10000:
                    raise ValueError()
            except (ValueError, TypeError):
                invalid.append(row['id'])
        if invalid:
            raise click.ClickException(f'Licenças inválidas (IDs): {invalid}')
        click.echo('Dados de licença válidos.')
