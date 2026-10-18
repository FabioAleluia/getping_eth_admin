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

    @app.cli.command('security-check')
    @click.option('--strict', is_flag=True, help='Retorna erro quando há recomendações pendentes.')
    def security_check(strict):
        """Verifica banco/configuração sem alterar registros nem revelar segredos."""
        from core.licensing import effective_status
        from werkzeug.security import check_password_hash
        warnings = []
        if app.config['ENVIRONMENT'] != 'production':
            warnings.append('Ambiente de desenvolvimento: use WSGI/HTTPS antes de publicar.')
        if not app.config['SESSION_COOKIE_SECURE']:
            warnings.append('Cookie sem Secure: adequado apenas a testes por HTTP.')
        if not app.config['REQUIRE_FINGERPRINT']:
            warnings.append('Fingerprint obrigatório desativado: compatibilidade com clientes antigos.')
        try:
            with get_db() as conn:
                if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise click.ClickException('Falha de integridade SQLite.')
                if conn.execute('PRAGMA foreign_key_check').fetchone():
                    raise click.ClickException('Referências inconsistentes no banco.')
                if not conn.execute('SELECT 1 FROM schema_migrations WHERE version=1').fetchone():
                    raise click.ClickException('Migrações pendentes. Execute init-db após backup.')
                conn.execute('SELECT id FROM admin_audit LIMIT 1')
                conn.execute('SELECT count FROM request_limits LIMIT 1')
                accounts = conn.execute('SELECT senha_hash FROM admin_usuarios WHERE ativo=1').fetchall()
                if not accounts:
                    warnings.append('Nenhuma conta administrativa ativa.')
                if any(check_password_hash(row[0], 'administrator') for row in accounts):
                    warnings.append('Há conta ativa com senha antiga proibida. Use reset-password.')
                missing = conn.execute(f"""SELECT COUNT(*) FROM licencas l
                    JOIN clientes c ON c.id=l.cliente_id
                    WHERE ({effective_status()})='ativa'
                    AND (instancia_fingerprint IS NULL OR trim(instancia_fingerprint)='')""").fetchone()[0]
                click.echo(f'Licenças ativas sem vínculo: {missing}.')
        except sqlite3.DatabaseError:
            raise click.ClickException('Estrutura do banco indisponível. Verifique backup e migrações.')
        click.echo('Estrutura e integridade do banco verificadas.')
        click.echo('HTTPS, firewall, certificados e configuração do cliente exigem verificação no ambiente.')
        for warning in warnings:
            click.echo(f'PENDENTE: {warning}')
        if strict and warnings:
            raise click.ClickException('Há recomendações de segurança pendentes.')
