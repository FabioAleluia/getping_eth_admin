import sqlite3
from pathlib import Path
from flask import Flask, request, jsonify, render_template
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from database.db import init_db, get_db


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config.update(config or {})
    secret = app.config.get('SECRET_KEY')
    if not isinstance(secret, str) or len(secret) < 32 or secret == 'getping-admin-super-secret-key-change-in-production':
        raise RuntimeError('Configure SECRET_KEY com um segredo aleatório de pelo menos 32 caracteres.')
    if app.testing:
        # Tests must explicitly opt into a database under a temporary directory.
        import tempfile
        db_path = Path(app.config['DATABASE']).resolve()
        if Path(tempfile.gettempdir()).resolve() not in db_path.parents:
            raise RuntimeError('TESTING exige DATABASE em diretório temporário.')
    if app.config['TRUSTED_PROXY_HOPS']:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=app.config['TRUSTED_PROXY_HOPS'],
                               x_proto=app.config['TRUSTED_PROXY_HOPS'])
    from core.security import gerar_csrf_token, validar_csrf_token
    from core.validation import validate_form
    from core.limits import request_limits
    # Run before auth so API behavior never depends on a panel login cookie.
    app.before_request(request_limits)
    app.before_request(validate_form)
    @app.before_request
    def check_csrf():
        if request.method in ('POST','PUT','PATCH','DELETE') and request.blueprint != 'api':
            validar_csrf_token()
    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.clientes import clientes_bp
    from routes.licencas import licencas_bp
    from routes.usuarios import usuarios_bp
    from routes.api import api_bp
    for bp in (auth_bp, dashboard_bp, clientes_bp, licencas_bp, usuarios_bp, api_bp):
        app.register_blueprint(bp)
    from core.pagination import pagination_context
    @app.context_processor
    def common_context():
        return dict(csrf_token=gerar_csrf_token, **pagination_context())
    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith('/api/'):
            response = jsonify(valido=False, status='erro', motivo=error.description)
            response.status_code = error.code
        else:
            response = app.make_response((render_template('error.html', error=error), error.code))
        if error.code == 429:
            response.headers['Retry-After'] = str(app.config['RATE_WINDOW_SECONDS'])
        return response
    @app.errorhandler(sqlite3.IntegrityError)
    def integrity_error(error):
        app.logger.warning('Conflito de integridade em %s', request.endpoint)
        from werkzeug.exceptions import Conflict
        return http_error(Conflict('Dados conflitantes ou inválidos. Revise os campos.'))
    @app.errorhandler(sqlite3.OperationalError)
    def database_error(error):
        app.logger.exception('Falha de banco')
        from werkzeug.exceptions import ServiceUnavailable
        return http_error(ServiceUnavailable('Serviço temporariamente indisponível.'))
    @app.errorhandler(500)
    def internal_error(error):
        if request.path.startswith('/api/'):
            return jsonify(valido=False, status='erro', motivo='Erro interno do serviço.'), 500
        return render_template('error.html', error=error), 500
    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = ("default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "font-src 'self' https://cdnjs.cloudflare.com; img-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        response.headers['Cache-Control'] = 'no-store'
        if request.is_secure and app.config['ENVIRONMENT'] == 'production':
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response
    from core.commands import register_commands
    register_commands(app)
    @app.get('/health')
    def health():
        with get_db() as conn:
            conn.execute('SELECT auth_version FROM admin_usuarios LIMIT 1')
        return jsonify(status='ok')
    if app.config['INIT_DB']:
        with app.app_context():
            init_db()
    return app


if __name__ == '__main__':
    create_app().run(host='0.0.0.0', port=5001, debug=False)
