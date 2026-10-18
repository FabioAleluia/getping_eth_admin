"""Fábrica e registro dos componentes do painel GetPing."""

import sqlite3
import tempfile
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request
from werkzeug.exceptions import Conflict, HTTPException, ServiceUnavailable
from werkzeug.middleware.proxy_fix import ProxyFix

from getping_admin.commands import register_commands
from getping_admin.config import load_config
from getping_admin.database.db import get_db
from getping_admin.database.migrate import init_db


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(load_config(app.instance_path, config))
    validate_config(app)
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
    if app.testing:
        # Tests must explicitly opt into a database under a temporary directory.
        db_path = Path(app.config["DATABASE"]).resolve()
        if Path(tempfile.gettempdir()).resolve() not in db_path.parents:
            raise RuntimeError("TESTING exige DATABASE em diretório temporário.")


def register_hooks(app):
    from getping_admin.limits import request_limits
    from getping_admin.security import gerar_csrf_token, validar_csrf_token

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
            conn.execute("SELECT auth_version FROM admin_usuarios LIMIT 1")
            conn.execute("SELECT count FROM request_limits LIMIT 1")
            conn.execute("SELECT id FROM admin_audit LIMIT 1")
            if not conn.execute("SELECT 1 FROM schema_migrations WHERE version=1").fetchone():
                abort(503, description="Migrações pendentes.")
        return jsonify(status="ok")
