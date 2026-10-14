import unittest
from app import create_app
from database.db import get_db, init_db

class TestAdministratorTrocaSenha(unittest.TestCase):
    def setUp(self):
        # Reinicializa DB garantindo o estado inicial
        init_db()
        from werkzeug.security import generate_password_hash
        with get_db() as conn:
            conn.execute("UPDATE admin_usuarios SET senha_hash = ?, trocar_senha = 1 WHERE username = 'administrator'", (generate_password_hash("administrator"),))
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def _get_csrf_token(self):
        with self.client.session_transaction() as sess:
            return sess.get("_csrf_token")

    def test_01_usuario_unico_administrator_no_banco(self):
        with get_db() as conn:
            u = conn.execute("SELECT * FROM admin_usuarios WHERE username = 'administrator'").fetchone()
            self.assertIsNotNone(u)
            self.assertEqual(u["username"], "administrator")
            self.assertEqual(u["papel"], "superadmin")
            self.assertEqual(u["trocar_senha"], 1)
            self.assertEqual(u["trocar_senha"], 1)

    def test_02_login_primeira_vez_forca_troca_de_senha(self):
        # 1. Faz login com administrator / administrator
        self.client.get("/login")
        token = self._get_csrf_token()

        resp_login = self.client.post("/login", data={
            "username": "administrator",
            "senha": "administrator",
            "csrf_token": token
        }, follow_redirects=True)

        self.assertEqual(resp_login.status_code, 200)
        # Deve ter sido redirecionado para a página de primeiro acesso
        self.assertIn("Primeiro Acesso".encode("utf-8"), resp_login.data)
        self.assertIn("/primeiro-acesso".encode("utf-8"), resp_login.data)

        # 2. Tentar acessar rotas protegidas (Dashboard, Clientes, Licenças) sem ter trocado a senha
        resp_dash = self.client.get("/", follow_redirects=True)
        self.assertIn("Primeiro Acesso".encode("utf-8"), resp_dash.data)

        resp_cli = self.client.get("/clientes/", follow_redirects=True)
        self.assertIn("Primeiro Acesso".encode("utf-8"), resp_cli.data)

        resp_lic = self.client.get("/licencas/", follow_redirects=True)
        self.assertIn("Primeiro Acesso".encode("utf-8"), resp_lic.data)

    def test_03_validacoes_complexidade_senha(self):
        # Login inicial
        self.client.get("/login")
        token = self._get_csrf_token()
        self.client.post("/login", data={
            "username": "administrator",
            "senha": "administrator",
            "csrf_token": token
        }, follow_redirects=True)

        token = self._get_csrf_token()

        # A) Senha com menos de 8 caracteres
        resp_curta = self.client.post("/primeiro-acesso", data={
            "nova_senha": "123@abc",
            "confirma_senha": "123@abc",
            "csrf_token": token
        }, follow_redirects=True)
        self.assertIn("mínimo 8 caracteres".encode("utf-8"), resp_curta.data)

        # B) Senha com 8 caracteres mas SEM especial
        token = self._get_csrf_token()
        resp_sem_esp = self.client.post("/primeiro-acesso", data={
            "nova_senha": "Senha123456",
            "confirma_senha": "Senha123456",
            "csrf_token": token
        }, follow_redirects=True)
        self.assertIn("pelo menos um caractere especial".encode("utf-8"), resp_sem_esp.data)

        # C) Senha igual a administrator
        token = self._get_csrf_token()
        resp_igual = self.client.post("/primeiro-acesso", data={
            "nova_senha": "administrator",
            "confirma_senha": "administrator",
            "csrf_token": token
        }, follow_redirects=True)
        self.assertIn("não pode ser igual à senha padrão".encode("utf-8"), resp_igual.data)

        # D) Senhas divergentes
        token = self._get_csrf_token()
        resp_div = self.client.post("/primeiro-acesso", data={
            "nova_senha": "Senha@Forte2026",
            "confirma_senha": "Outra@Senha2026",
            "csrf_token": token
        }, follow_redirects=True)
        self.assertIn("confirmação de senha não confere".encode("utf-8"), resp_div.data)

    def test_04_sucesso_troca_senha_e_acesso_livre(self):
        # Login inicial
        self.client.get("/login")
        token = self._get_csrf_token()
        self.client.post("/login", data={
            "username": "administrator",
            "senha": "administrator",
            "csrf_token": token
        }, follow_redirects=True)

        token = self._get_csrf_token()
        nova_senha_segura = "Super@Admin#2026"

        resp_ok = self.client.post("/primeiro-acesso", data={
            "nova_senha": nova_senha_segura,
            "confirma_senha": nova_senha_segura,
            "csrf_token": token
        }, follow_redirects=True)

        self.assertEqual(resp_ok.status_code, 200)
        self.assertIn("Senha alterada com sucesso".encode("utf-8"), resp_ok.data)
        self.assertIn("Visão Geral".encode("utf-8"), resp_ok.data)

        # Verifica no banco que trocar_senha virou 0
        with get_db() as conn:
            u = conn.execute("SELECT trocar_senha FROM admin_usuarios WHERE username = 'administrator'").fetchone()
            self.assertEqual(u["trocar_senha"], 0)

        # Faz logout
        self.client.get("/logout")

        # Testa login com a senha antiga 'administrator' (deve falhar)
        self.client.get("/login")
        token = self._get_csrf_token()
        resp_falha = self.client.post("/login", data={
            "username": "administrator",
            "senha": "administrator",
            "csrf_token": token
        }, follow_redirects=True)
        self.assertIn("Credenciais inválidas".encode("utf-8"), resp_falha.data)

        # Testa login com a NOVA senha segura (deve entrar direto no Dashboard)
        token = self._get_csrf_token()
        resp_sucesso = self.client.post("/login", data={
            "username": "administrator",
            "senha": nova_senha_segura,
            "csrf_token": token
        }, follow_redirects=True)
        self.assertEqual(resp_sucesso.status_code, 200)
        self.assertIn("Visão Geral".encode("utf-8"), resp_sucesso.data)
        self.assertNotIn("Primeiro Acesso".encode("utf-8"), resp_sucesso.data)

if __name__ == "__main__":
    unittest.main()
