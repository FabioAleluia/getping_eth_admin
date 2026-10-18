"""Verifica recursos do wheel instalado. Execute com python -I fora do repositório."""

import re
import secrets
import tempfile
from pathlib import Path

from getping_admin import create_app


def main():
    with tempfile.TemporaryDirectory(prefix="getping-installed-") as directory:
        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": secrets.token_hex(32),
                "DATABASE": str(Path(directory) / "instance/app.db"),
                "SESSION_COOKIE_SECURE": False,
            }
        )
        result = app.test_cli_runner().invoke(args=["init-db"])
        if result.exit_code:
            raise RuntimeError(result.output) from result.exception
        client = app.test_client()
        if client.get("/health").json != {"status": "ok"}:
            raise RuntimeError("Schema ou migração ausente no pacote.")
        with app.app_context():
            # Parse every packaged template, including forms not visited by the smoke test.
            templates = app.jinja_env.list_templates()
            resources = set()
            required = {"base.html", "error.html", "auth/login.html", "licencas/form.html"}
            if not required.issubset(templates):
                raise RuntimeError(
                    f"Templates essenciais ausentes: {required.difference(templates)}"
                )
            for name in templates:
                app.jinja_env.get_template(name)
                source, _, _ = app.jinja_env.loader.get_source(app.jinja_env, name)
                resources.update(
                    re.findall(r"""url_for\(['"]static['"],\s*filename=['"]([^'"]+)""", source)
                )
        login = client.get("/login")
        if login.status_code != 200:
            raise RuntimeError("Template de login indisponível.")
        for filename in resources:
            with client.get("/static/" + filename) as response:
                if response.status_code != 200 or not response.data:
                    raise RuntimeError(f"Recurso estático ausente: {filename!r}")
        response = client.post("/api/v1/licenca/validar", json={"chave_licenca": "missing"})
        if response.status_code != 404 or response.json["valido"]:
            raise RuntimeError("Contrato de erro da API inválido.")
    print("Wheel instalado: templates, CSS, JS, schema, migração, CLI e API verificados.")


if __name__ == "__main__":
    main()
