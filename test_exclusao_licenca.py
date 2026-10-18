import unittest
from tests.support import IsolatedDatabaseTestCase
from app import create_app
from database.db import get_db

class TestExclusaoLicenca(IsolatedDatabaseTestCase):
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

    def test_fluxo_exclusao_licenca_e_cliente(self):
        # 1. Obter página de login para gerar sessão e token
        self.client.get("/login")
        token = self._get_csrf_token()

        resp_login = self.client.post("/login", data={
            "username": "administrator",
            "senha": "SenhaForte@123",
            "csrf_token": token
        }, follow_redirects=True)
        self.assertEqual(resp_login.status_code, 200)

        # 2. Criar Cliente
        nome_empresa_teste = "Cliente Exclusao Unico Ltda"
        token = self._get_csrf_token()
        resp_c = self.client.post("/clientes/novo", data={
            "nome_empresa": nome_empresa_teste,
            "responsavel_nome": "Marcos Teste",
            "csrf_token": token
        }, follow_redirects=True)
        self.assertEqual(resp_c.status_code, 200)

        with get_db() as conn:
            cliente = conn.execute("SELECT id FROM clientes WHERE nome_empresa = ? ORDER BY id DESC", (nome_empresa_teste,)).fetchone()
            cliente_id = cliente["id"]

        # 3. Criar Licença
        token = self._get_csrf_token()
        resp_l = self.client.post("/licencas/nova", data={
            "cliente_id": cliente_id,
            "tipo_plano": "Basico",
            "limite_hosts": 10,
            "limite_agentes": 5,
            "dias_validade": 30,
            "csrf_token": token
        }, follow_redirects=True)
        self.assertEqual(resp_l.status_code, 200)

        with get_db() as conn:
            lic = conn.execute("SELECT id, chave_licenca FROM licencas WHERE cliente_id = ?", (cliente_id,)).fetchone()
            lic_id = lic["id"]
            chave = lic["chave_licenca"]

        # 4. Tentar excluir o cliente antes da licença (DEVE SER BLOQUEADO)
        token = self._get_csrf_token()
        resp_del_c = self.client.post(f"/clientes/{cliente_id}/excluir", data={"csrf_token": token}, follow_redirects=True)
        self.assertIn("Não é possível excluir o cliente pois ele possui".encode("utf-8"), resp_del_c.data)

        # 5. Excluir a licença
        token = self._get_csrf_token()
        resp_del_l = self.client.post(f"/licencas/{lic_id}/excluir", data={"csrf_token": token}, follow_redirects=True)
        self.assertEqual(resp_del_l.status_code, 200)
        self.assertIn("foi excluída com sucesso".encode("utf-8"), resp_del_l.data)

        # Confirma que a licença não existe mais no banco
        with get_db() as conn:
            check_lic = conn.execute("SELECT id FROM licencas WHERE id = ?", (lic_id,)).fetchone()
            self.assertIsNone(check_lic)

        # 6. Validar que o GetPing agora recebe 404 ao consultar a chave excluída
        resp_api = self.client.post("/api/v1/licenca/validar", json={"chave_licenca": chave})
        self.assertEqual(resp_api.status_code, 404)

        # 7. Agora tentar excluir o cliente novamente (DEVE FUNCIONAR)
        token = self._get_csrf_token()
        resp_del_c2 = self.client.post(f"/clientes/{cliente_id}/excluir", data={"csrf_token": token}, follow_redirects=True)
        self.assertIn("Cliente excluído com sucesso".encode("utf-8"), resp_del_c2.data)

        # Confirma que o cliente não existe mais
        with get_db() as conn:
            check_cli = conn.execute("SELECT id FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
            self.assertIsNone(check_cli)

    def test_bloqueio_gestor_exclusao(self):
        # Cria um usuário gestor no banco se não existir
        from werkzeug.security import generate_password_hash
        with get_db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO admin_usuarios (nome, username, email, senha_hash, papel, ativo, trocar_senha, criado_em) "
                "VALUES ('Gestor Teste', 'gestor1', 'gestor@teste.com', ?, 'gestor', 1, 0, '2026-01-01 00:00:00')",
                (generate_password_hash("gestor123"),)
            )

        # Inicia sessão e faz login como gestor
        self.client.get("/login")
        token = self._get_csrf_token()

        self.client.post("/login", data={
            "username": "gestor1",
            "senha": "gestor123",
            "csrf_token": token
        }, follow_redirects=True)

        token = self._get_csrf_token()
        # Tentar excluir uma licença qualquer
        resp = self.client.post("/licencas/1/excluir", data={"csrf_token": token}, follow_redirects=True)
        self.assertIn("Apenas usuários com perfil Superadmin podem excluir".encode("utf-8"), resp.data)

    def test_bloqueio_csrf_invalido(self):
        # Tenta postar sem CSRF token
        self.client.get("/login")
        resp = self.client.post("/login", data={"username": "administrator", "senha": "SenhaForte@123"})
        self.assertEqual(resp.status_code, 400)

if __name__ == "__main__":
    unittest.main()
