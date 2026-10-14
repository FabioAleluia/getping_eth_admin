from flask import Flask
from config import Config
from database.db import init_db

# Importação dos Blueprints
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.clientes import clientes_bp
from routes.licencas import licencas_bp
from routes.usuarios import usuarios_bp
from routes.api import api_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Inicializa banco de dados
    init_db()

    # Registro de Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(clientes_bp)
    app.register_blueprint(licencas_bp)
    app.register_blueprint(usuarios_bp)
    app.register_blueprint(api_bp)

    from core.security import gerar_csrf_token, validar_csrf_token
    from flask import request

    @app.context_processor
    def inject_csrf_token():
        return dict(csrf_token=gerar_csrf_token)

    @app.before_request
    def check_csrf():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            # Permite requisições da API pública sem CSRF (elas usam chave de licença/token)
            if not request.path.startswith("/api/"):
                validar_csrf_token()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
