import unittest
from app import create_app
from database.db import get_db, init_db

class TestModuloUsuarios(unittest.TestCase):
    def setUp(self):
        init_db()
        from werkzeug.security import generate_password_hash
        with get_db() as conn:
            conn.execute("DELETE FROM admin_usuarios WHERE username != 'administrator'")
            conn.execute(
                "UPDATE admin_usuarios SET senha_hash = ?, trocar_senha = 0 WHERE username = 'administrator'",
                (generate_password_hash("SenhaForte@123"),)
            )
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def _get_csrf_token(self):
        with self.client.session_transaction() as sess:
            return sess.get("_csrf_token")

    def _login(self, username="administrator", senha="SenhaForte@123"):
        self.client.get("/login")
        token = self._get_csrf_token()
        return self.client.post("/login", data={
            "username": username,
            "senha": senha,
            "csrf_token": token
        }, follow_redirects=True)

    def test_01_listagem_usuarios(self):
        self._login()
        resp = self.client.get("/usuarios/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Gestão de Usuários".encode("utf-8"), resp.data)
        self.assertIn("administrator".encode("utf-8"), resp.data)
        self.assertIn("Superadmin".encode("utf-8"), resp.data)

    def test_02_cadastrar_gestor_e_assistente(self):
        self._login()

        # Cadastrar Gestor
        token = self._get_csrf_token()
        resp_g = self.client.post("/usuarios/novo", data={
            "nome": "Carlos Gestor",
            "username": "carlos.gestor",
            "email": "carlos@gestor.com",
            "papel": "gestor",
            "senha_inicial": "Gestor@2026!",
            "exigir_troca": "1",
            "csrf_token": token
        }, follow_redirects=True)
        self.assertEqual(resp_g.status_code, 200)
        self.assertIn("cadastrado com sucesso".encode("utf-8"), resp_g.data)
        self.assertIn("carlos.gestor".encode("utf-8"), resp_g.data)

        # Cadastrar Assistente
        token = self._get_csrf_token()
        resp_a = self.client.post("/usuarios/novo", data={
            "nome": "Ana Assistente",
            "username": "ana.assistente",
            "email": "ana@assistente.com",
            "papel": "assistente",
            "senha_inicial": "Assistente@2026#",
            "exigir_troca": "1",
            "csrf_token": token
        }, follow_redirects=True)
        self.assertEqual(resp_a.status_code, 200)
        self.assertIn("cadastrado com sucesso".encode("utf-8"), resp_a.data)
        self.assertIn("ana.assistente".encode("utf-8"), resp_a.data)

        # Verifica no banco se ambos estão com seus devidos papéis e trocar_senha = 1
        with get_db() as conn:
            u_g = conn.execute("SELECT * FROM admin_usuarios WHERE username = 'carlos.gestor'").fetchone()
            self.assertEqual(u_g["papel"], "gestor")
            self.assertEqual(u_g["trocar_senha"], 1)

            u_a = conn.execute("SELECT * FROM admin_usuarios WHERE username = 'ana.assistente'").fetchone()
            self.assertEqual(u_a["papel"], "assistente")
            self.assertEqual(u_a["trocar_senha"], 1)

    def test_03_login_novo_usuario_com_troca_obrigatoria(self):
        # 1. Cria usuário com trocar_senha = 1
        from werkzeug.security import generate_password_hash
        with get_db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO admin_usuarios (nome, username, email, senha_hash, papel, ativo, trocar_senha, criado_em) "
                "VALUES ('Marcos Assistente', 'marcos.ass', 'marcos@test.com', ?, 'assistente', 1, 1, '2026-01-01 00:00:00')",
                (generate_password_hash("SenhaInit@2026"),)
            )

        # 2. Faz login com o usuário criado
        self.client.get("/login")
        token = self._get_csrf_token()
        resp_log = self.client.post("/login", data={
            "username": "marcos.ass",
            "senha": "SenhaInit@2026",
            "csrf_token": token
        }, follow_redirects=True)

        # Deve ser forçado a ir para /primeiro-acesso
        self.assertEqual(resp_log.status_code, 200)
        self.assertIn("Primeiro Acesso".encode("utf-8"), resp_log.data)

        # 3. Realiza a troca obrigatória
        token = self._get_csrf_token()
        resp_troca = self.client.post("/primeiro-acesso", data={
            "nova_senha": "NovaSenha@Marcos2026",
            "confirma_senha": "NovaSenha@Marcos2026",
            "csrf_token": token
        }, follow_redirects=True)
        self.assertEqual(resp_troca.status_code, 200)
        self.assertIn("Visão Geral".encode("utf-8"), resp_troca.data)

    def test_04_protecoes_seguranca_exclusao(self):
        self._login()
        token = self._get_csrf_token()

        # A) Tentar excluir o administrator master (deve ser bloqueado)
        with get_db() as conn:
            admin_user = conn.execute("SELECT id FROM admin_usuarios WHERE username = 'administrator'").fetchone()
            admin_id = admin_user["id"]

        resp_del_admin = self.client.post(f"/usuarios/{admin_id}/excluir", data={"csrf_token": token}, follow_redirects=True)
        self.assertIn("não pode ser excluído".encode("utf-8"), resp_del_admin.data)

        # B) Tentar excluir um assistente (deve ter sucesso)
        with get_db() as conn:
            ass_user = conn.execute("SELECT id FROM admin_usuarios WHERE papel = 'assistente' ORDER BY id DESC").fetchone()
            if ass_user:
                ass_id = ass_user["id"]
                token = self._get_csrf_token()
                resp_del = self.client.post(f"/usuarios/{ass_id}/excluir", data={"csrf_token": token}, follow_redirects=True)
                self.assertIn("excluído com sucesso".encode("utf-8"), resp_del.data)

if __name__ == "__main__":
    unittest.main()
