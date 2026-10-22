"""Fábrica e registro dos componentes do painel GetPing."""

import sqlite3
import tempfile
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request
from werkzeug.exceptions import Conflict, HTTPException, ServiceUnavailable
from werkzeug.middleware.proxy_fix import ProxyFix

from getping_admin.commands import register_commands
from getping_admin.config import load_config
from getping_admin.database.db import get_db
from getping_admin.database.diagnostics import schema_issues
from getping_admin.database.migrate import init_db


class HTTPSRequired(HTTPException):
    code = 426
    description = "HTTPS obrigatório. Atualize a URL do servidor para HTTPS."


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(load_config(app.instance_path, config))
    validate_config(app)
    from getping_admin.license_protocol import load_private

    if app.config["LICENSE_SIGNING_KEY_FILE"]:
        if app.config["ENVIRONMENT"] == "production" and not app.testing:
            if Path(app.config["LICENSE_SIGNING_KEY_FILE"]).stat().st_mode & 0o077:
                raise RuntimeError("Proteja a chave privada de emissão com permissão 0600.")
        app.extensions["license_signer"] = load_private(
            Path(app.config["LICENSE_SIGNING_KEY_FILE"]).read_bytes()
        )
    if app.config["ENVIRONMENT"] == "production" and not app.testing:
        if not app.config["REQUIRE_HTTPS"] or not app.config["REQUIRE_FINGERPRINT"]:
            raise RuntimeError("Produção exige HTTPS e vínculo de instalação obrigatórios.")
        if "license_signer" not in app.extensions:
            raise RuntimeError("Produção exige GETPING_LICENSE_SIGNING_KEY_FILE (Ed25519).")

    if app.config["TRUSTED_PROXY_HOPS"]:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=app.config["TRUSTED_PROXY_HOPS"],
            x_proto=app.config["TRUSTED_PROXY_HOPS"],
        )
    register_hooks(app)
    register_blueprints(app)
    register_error_handlers(app)
    register_commands(app)
    register_health_check(app)
    if app.config["INIT_DB"]:
        with app.app_context():
            init_db()
    return app


def validate_config(app):
    secret = app.config.get("SECRET_KEY")
    if (
        not isinstance(secret, str)
        or len(secret) < 32
        or secret == "getping-admin-super-secret-key-change-in-production"
    ):
        raise RuntimeError(
            "Configure SECRET_KEY com um segredo aleatório de pelo menos 32 caracteres."
        )
    if app.config["REQUIRE_HTTPS"]:
        from urllib.parse import urlsplit

        parsed = urlsplit(app.config["PUBLIC_BASE_URL"])
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise RuntimeError(
                "GETPING_PUBLIC_BASE_URL deve ser uma origem HTTPS válida, sem caminho ou credenciais."
            )
        if not app.config["SESSION_COOKIE_SECURE"]:
            raise RuntimeError("HTTPS obrigatório exige SESSION_COOKIE_SECURE=True.")
    if app.testing:
        # Tests must explicitly opt into a database under a temporary directory.
        db_path = Path(app.config["DATABASE"]).resolve()
        if Path(tempfile.gettempdir()).resolve() not in db_path.parents:
            raise RuntimeError("TESTING exige DATABASE em diretório temporário.")


def register_hooks(app):
    from getping_admin.limits import request_limits
    from getping_admin.security import gerar_csrf_token, validar_csrf_token

    @app.before_request
    def require_https():
        if app.config["REQUIRE_HTTPS"] and not request.is_secure and request.endpoint != "health":
            if request.method not in ("GET", "HEAD") or request.path.startswith("/api/"):
                raise HTTPSRequired()
            origin = app.config["PUBLIC_BASE_URL"].rstrip("/")
            return redirect(origin + request.full_path.rstrip("?"), code=308)

    # Run before auth so API behavior never depends on a panel login cookie.
    app.before_request(request_limits)

    @app.before_request
    def check_csrf():
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.blueprint != "api":
            validar_csrf_token()

    from getping_admin.auth import carregar_usuario_logado

    app.before_request(carregar_usuario_logado)
    from getping_admin.pagination import pagination_context

    @app.context_processor
    def common_context():
        return dict(csrf_token=gerar_csrf_token, **pagination_context())

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "font-src 'self' https://cdnjs.cloudflare.com; img-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        if request.is_secure and app.config["ENVIRONMENT"] == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response


def register_blueprints(app):
    from getping_admin.routes.api import api_bp
    from getping_admin.routes.audit import audit_bp
    from getping_admin.routes.auth import auth_bp
    from getping_admin.routes.clientes import clientes_bp
    from getping_admin.routes.dashboard import dashboard_bp
    from getping_admin.routes.licencas import licencas_bp
    from getping_admin.routes.usuarios import usuarios_bp

    for bp in (auth_bp, dashboard_bp, clientes_bp, licencas_bp, usuarios_bp, api_bp, audit_bp):
        app.register_blueprint(bp)


def register_error_handlers(app):
    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            response = jsonify(valido=False, status="erro", motivo=error.description)
            response.status_code = error.code
        else:
            response = app.make_response((render_template("error.html", error=error), error.code))
        if error.code == 429:
            response.headers["Retry-After"] = str(app.config["RATE_WINDOW_SECONDS"])
        return response

    @app.errorhandler(sqlite3.IntegrityError)
    def integrity_error(error):
        app.logger.warning("Conflito de integridade em %s", request.endpoint)
        return http_error(Conflict("Dados conflitantes ou inválidos. Revise os campos."))

    @app.errorhandler(sqlite3.OperationalError)
    def database_error(error):
        app.logger.exception("Falha de banco")
        return http_error(ServiceUnavailable("Serviço temporariamente indisponível."))

    @app.errorhandler(500)
    def internal_error(error):
        if request.path.startswith("/api/"):
            return jsonify(valido=False, status="erro", motivo="Erro interno do serviço."), 500
        return render_template("error.html", error=error), 500


def register_health_check(app):
    @app.get("/health")
    def health():
        with get_db() as conn:
            if schema_issues(conn):
                abort(503, description="Estrutura do banco indisponível ou migrações pendentes.")
        return jsonify(status="ok")
