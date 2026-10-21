import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
from werkzeug.security import generate_password_hash

from getping_admin.audit import audit
from getping_admin.database.db import database_path, get_db
from getping_admin.database.diagnostics import schema_issues
from getping_admin.database.migrate import init_db
from getping_admin.identity import identity_conflict, invalid_identity_ids, normalize_identifier
from getping_admin.licensing import invalid_license_ids
from getping_admin.security import validar_complexidade_senha


def register_commands(app):
    @app.cli.command("init-db")
    def initialize():
        """Aplica schema e migrações; preserve backup antes de atualizar."""
        try:
            init_db()
        except RuntimeError as error:
            raise click.ClickException(str(error)) from error
        click.echo("Schema e migrações aplicados. Nenhuma senha foi criada ou alterada.")

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(email, password):
        """Provisiona o administrador inicial apenas quando ainda não há superadmin."""
        valid, message = validar_complexidade_senha(password)
        if not valid:
            raise click.ClickException(message)
        email = normalize_identifier(email)
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
            raise click.ClickException("E-mail inválido.")
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM admin_usuarios WHERE papel='superadmin'").fetchone():
                raise click.ClickException(
                    "Já existe superadmin. Use o painel para administrar contas."
                )
            if identity_conflict(conn, "administrator", email):
                raise click.ClickException("Nome de usuário ou e-mail já cadastrado.")
            cursor = conn.execute(
                """INSERT INTO admin_usuarios
                (nome,username,email,senha_hash,papel,ativo,trocar_senha,criado_em)
                VALUES ('Administrador Master','administrator',?,?,'superadmin',1,1,?)""",
                (
                    email,
                    generate_password_hash(password),
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            audit(conn, "create", "usuario", cursor.lastrowid, after={"papel": "superadmin"})
        click.echo("Administrador criado. Troca de senha exigida no primeiro acesso.")

    @app.cli.command("reset-password")
    @click.argument("username")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def reset_password(username, password):
        """Recuperação local: redefine senha, revoga sessões e reativa a conta."""
        valid, message = validar_complexidade_senha(password)
        if not valid:
            raise click.ClickException(message)
        with get_db() as conn:
            matches = conn.execute(
                "SELECT id FROM admin_usuarios WHERE lower(trim(username))=? LIMIT 2",
                (normalize_identifier(username),),
            ).fetchall()
            if len(matches) != 1:
                raise click.ClickException("Usuário não encontrado.")
            user = matches[0]
            conn.execute(
                "UPDATE admin_usuarios SET senha_hash=?, auth_version=auth_version+1, ativo=1, trocar_senha=1 WHERE id=?",
                (generate_password_hash(password), user["id"]),
            )
            audit(conn, "local_password_reset", "usuario", user["id"])
        click.echo("Senha redefinida. Sessões revogadas; troca obrigatória no próximo acesso.")

    @app.cli.command("backup-db")
    @click.argument("destination", type=click.Path(path_type=Path))
    def backup(destination):
        """Backup SQLite consistente incluindo WAL; não sobrescreve arquivos."""
        if destination.resolve() == database_path():
            raise click.ClickException("Destino deve ser diferente do banco original.")
        try:
            with destination.open("xb"):
                pass
        except FileExistsError:
            raise click.ClickException("Destino já existe.")
        try:
            destination.chmod(0o600)
            with get_db() as source, sqlite3.connect(destination) as target:
                source.backup(target)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        click.echo("Backup concluído.")

    @app.cli.command("prune-logs")
    def prune():
        """Remove logs de validação antigos; preserva auditoria administrativa."""
        days = app.config["LOG_RETENTION_DAYS"]
        if not isinstance(days, int) or days < 1:
            raise click.ClickException("LOG_RETENTION_DAYS precisa ser positivo.")
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            count = conn.execute("DELETE FROM licenca_logs WHERE criado_em < ?", (cutoff,)).rowcount
            import time

            window = int(time.time()) // app.config["RATE_WINDOW_SECONDS"]
            conn.execute("DELETE FROM request_limits WHERE window < ?", (window - 1,))
        click.echo(f"{count} logs antigos removidos. Auditoria administrativa preservada.")

    @app.cli.command("check-data")
    def check_data():
        """Relata IDs de licenças legadas inválidas sem alterá-las."""
        with get_db() as conn:
            invalid = invalid_license_ids(conn)
            invalid_users = invalid_identity_ids(conn)
        if invalid:
            raise click.ClickException(f"Licenças inválidas (IDs): {invalid}")
        if invalid_users:
            raise click.ClickException(
                f"Identificadores conflitantes ou vazios (IDs): {invalid_users}"
            )
        click.echo("Dados de licença e identificadores válidos.")

    @app.cli.command("security-check")
    @click.option("--strict", is_flag=True, help="Retorna erro quando há recomendações pendentes.")
    def security_check(strict):
        """Verifica banco/configuração sem alterar registros nem revelar segredos."""
        from werkzeug.security import check_password_hash

        from getping_admin.licensing import effective_status

        warnings = []
        if app.config["ENVIRONMENT"] != "production":
            warnings.append("Ambiente de desenvolvimento: use WSGI/HTTPS antes de publicar.")
        if not app.config["SESSION_COOKIE_SECURE"]:
            warnings.append("Cookie sem Secure: adequado apenas a testes por HTTP.")
        if not app.config["REQUIRE_HTTPS"]:
            warnings.append("HTTPS obrigatório ainda não ativado na aplicação.")
        if not app.config["REQUIRE_FINGERPRINT"]:
            warnings.append(
                "Fingerprint obrigatório desativado: compatibilidade com clientes antigos."
            )
        try:
            with get_db() as conn:
                if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise click.ClickException("Falha de integridade SQLite.")
                if conn.execute("PRAGMA foreign_key_check").fetchone():
                    raise click.ClickException("Referências inconsistentes no banco.")
                issues = schema_issues(conn)
                if issues:
                    raise click.ClickException(" ".join(issues) + " Revise backup e migrações.")
                invalid = invalid_license_ids(conn)
                if invalid:
                    raise click.ClickException(f"Licenças inválidas (IDs): {invalid}")
                invalid_users = invalid_identity_ids(conn)
                if invalid_users:
                    raise click.ClickException(
                        f"Identificadores conflitantes ou vazios (IDs): {invalid_users}"
                    )
                accounts = conn.execute(
                    "SELECT senha_hash FROM admin_usuarios WHERE ativo=1"
                ).fetchall()
                if not accounts:
                    warnings.append("Nenhuma conta administrativa ativa.")
                if any(check_password_hash(row[0], "administrator") for row in accounts):
                    warnings.append("Há conta ativa com senha antiga proibida. Use reset-password.")
                missing = conn.execute(f"""SELECT COUNT(*) FROM licencas l
                    JOIN clientes c ON c.id=l.cliente_id
                    WHERE ({effective_status()})='ativa'
                    AND NOT EXISTS (SELECT 1 FROM license_bindings b WHERE b.licenca_id=l.id AND b.fingerprint IS NOT NULL)""").fetchone()[
                    0
                ]
                click.echo(f"Licenças ativas sem vínculo autorizado: {missing}.")
        except sqlite3.DatabaseError:
            raise click.ClickException(
                "Estrutura do banco indisponível. Verifique backup e migrações."
            )
        if missing:
            warnings.append(
                "Há licenças ativas aguardando vínculo autorizado; confira antes de exigir globalmente."
            )
        click.echo("Estrutura e integridade do banco verificadas.")
        click.echo(
            "HTTPS, firewall, certificados e configuração do cliente exigem verificação no ambiente."
        )
        for warning in warnings:
            click.echo(f"PENDENTE: {warning}")
        if strict and warnings:
            raise click.ClickException("Há recomendações de segurança pendentes.")
