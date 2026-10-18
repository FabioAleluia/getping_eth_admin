import unittest
from tests.support import IsolatedDatabaseTestCase
from app import create_app
from database.db import get_db

class TestGetPingAdmin(IsolatedDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.application
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        from werkzeug.security import generate_password_hash
        with get_db() as conn:
            conn.execute(
                "UPDATE admin_usuarios SET senha_hash = ?, trocar_senha = 0 WHERE username = 'administrator'",
                (generate_password_hash("SenhaForte@123"),)
            )

    def _get_csrf_token(self):
        with self.client.session_transaction() as sess:
            return sess.get("_csrf_token")

    def test_01_login_get(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"GetPing Admin", response.data)

    def test_02_login_sucesso(self):
        self.client.get("/login")
        token = self._get_csrf_token()
        response = self.client.post("/login", data={
            "username": "administrator",
            "senha": "SenhaForte@123",
            "csrf_token": token
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Vis", response.data)

    def test_03_cadastro_cliente_e_licenca(self):
        self.client.get("/login")
        token = self._get_csrf_token()
        self.client.post("/login", data={"username": "administrator", "senha": "SenhaForte@123", "csrf_token": token}, follow_redirects=True)

        token = self._get_csrf_token()
        resp_cliente = self.client.post("/clientes/novo", data={
            "nome_empresa": "Empresa Teste SA Fluxo",
            "responsavel_nome": "Carlos Roberto",
            "responsavel_email": "carlos@teste.com",
            "telefone": "11988887777",
            "cnpj_cpf": "12.345.678/0001-90",
            "observacoes": "Cliente de teste automatizado",
            "csrf_token": token
        }, follow_redirects=True)
        self.assertEqual(resp_cliente.status_code, 200)

        with get_db() as conn:
            cliente = conn.execute("SELECT id FROM clientes WHERE nome_empresa = 'Empresa Teste SA Fluxo' ORDER BY id DESC").fetchone()
            cliente_id = cliente["id"]

        token = self._get_csrf_token()
        resp_lic = self.client.post("/licencas/nova", data={
            "cliente_id": cliente_id,
            "tipo_plano": "Profissional",
            "limite_hosts": 50,
            "limite_agentes": 20,
            "dias_validade": 60,
            "observacoes": "Licença gerada no teste",
            "csrf_token": token
        }, follow_redirects=True)
        self.assertEqual(resp_lic.status_code, 200)

        with get_db() as conn:
            lic = conn.execute("SELECT chave_licenca FROM licencas WHERE cliente_id = ? ORDER BY id DESC", (cliente_id,)).fetchone()
            chave = lic["chave_licenca"]

        resp_api = self.client.post("/api/v1/licenca/validar", json={
            "chave_licenca": chave,
            "fingerprint": "MAQ-TESTE-UUID-999",
            "versao": "0.0.4"
        })
        self.assertEqual(resp_api.status_code, 200)
        dados = resp_api.get_json()
        self.assertTrue(dados["valido"])
        self.assertEqual(dados["cliente"], "Empresa Teste SA Fluxo")

    def test_04_api_licenca_invalida(self):
        resp_api = self.client.post("/api/v1/licenca/validar", json={
            "chave_licenca": "CHAVE-INEXISTENTE-123",
            "fingerprint": "MAQ-TESTE-UUID-999"
        })
        self.assertEqual(resp_api.status_code, 404)
        dados = resp_api.get_json()
        self.assertFalse(dados["valido"])

if __name__ == "__main__":
    unittest.main()
