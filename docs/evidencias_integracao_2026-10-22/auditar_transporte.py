"""Exercita o worker HTTP real somente em loopback, com CA temporária."""
# ruff: noqa: E402

import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT.parent / "GetPing_eth/getping_v0.0.4"
sys.path[:0] = [str(ROOT), str(CLIENT)]
import requests
from getping.licensing import _http_post
from werkzeug.serving import WSGIRequestHandler, make_server

from getping_admin import create_app


class SilentHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def run():
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    # Não usa proxies, CAs ou endpoints configurados no ambiente operacional.
    for name in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        os.environ.pop(name, None)
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    with tempfile.TemporaryDirectory(prefix="getping-tls-audit-") as directory:
        root = Path(directory)
        cert, key = root / "cert.pem", root / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-subj",
                "/CN=127.0.0.1",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
            ],
            check=True,
            capture_output=True,
        )
        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": secrets.token_hex(32),
                "DATABASE": str(root / "admin.db"),
                "INIT_DB": True,
                "API_RATE_LIMIT": 0,
                "REQUIRE_HTTPS": False,
            }
        )
        servers = []
        try:
            for tls in (False, True):
                server = make_server(
                    "127.0.0.1",
                    0,
                    app,
                    ssl_context=(str(cert), str(key)) if tls else None,
                    request_handler=SilentHandler,
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                servers.append((server, thread))
            payload = {"chave_licenca": "FIXTURE-ONLY", "fingerprint": "AUDIT-ONLY"}

            def endpoint(i, host="127.0.0.1"):
                return f"{'https' if i else 'http'}://{host}:{servers[i][0].server_port}/api/v1/licenca/validar"

            response = _http_post(endpoint(0), payload)
            assert response.status_code == 404
            print(
                json.dumps(
                    {"ensaio": "http_plaintext_aceito_pelo_worker", "http": response.status_code}
                )
            )
            try:
                _http_post(endpoint(1), payload)
                raise AssertionError("Certificado não confiável foi aceito")
            except requests.ConnectionError:
                print(json.dumps({"ensaio": "tls_ca_nao_confiavel", "rejeitado": True}))
            os.environ["REQUESTS_CA_BUNDLE"] = str(cert)
            response = _http_post(endpoint(1), payload)
            assert response.status_code == 404
            print(json.dumps({"ensaio": "tls_ca_confiavel", "http": response.status_code}))
            try:
                _http_post(endpoint(1, "localhost"), payload)
                raise AssertionError("Hostname incorreto foi aceito")
            except requests.ConnectionError:
                print(json.dumps({"ensaio": "tls_hostname_incorreto", "rejeitado": True}))
        finally:
            for server, thread in servers:
                server.shutdown()
                thread.join(timeout=3)
                server.server_close()


if __name__ == "__main__":
    run()
