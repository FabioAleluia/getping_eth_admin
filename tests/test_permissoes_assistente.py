import unittest

from werkzeug.security import generate_password_hash

from getping_admin.database.db import get_db
from getping_admin.database.migrate import init_db
from tests.support import IsolatedDatabaseTestCase


class TestPermissoesAssistente(IsolatedDatabaseTestCase):
    def setUp(self):
        super().setUp()
        init_db()
        with get_db() as conn:
            conn.execute("DELETE FROM licenca_logs")
            conn.execute("DELETE FROM licencas")
            conn.execute("DELETE FROM clientes")
            conn.execute("DELETE FROM admin_usuarios WHERE username != 'administrator'")

            # Atualiza administrator
            conn.execute(
                "UPDATE admin_usuarios SET senha_hash = ?, trocar_senha = 0 WHERE username = 'administrator'",
                (generate_password_hash("SenhaForte@123"),),
            )

            # Cria assistente
            conn.execute(
                """
                INSERT INTO admin_usuarios (nome, username, email, senha_hash, papel, ativo, trocar_senha, criado_em)
                VALUES ('Assistente Teste', 'user.assistente', 'ass@test.com', ?, 'assistente', 1, 0, '2026-01-01 00:00:00')
                """,
                (generate_password_hash("Assistente@2026#"),),
            )

            # Cria gestor
            conn.execute(
                """
                INSERT INTO admin_usuarios (nome, username, email, senha_hash, papel, ativo, trocar_senha, criado_em)
                VALUES ('Gestor Teste', 'user.gestor', 'gestor@test.com', ?, 'gestor', 1, 0, '2026-01-01 00:00:00')
                """,
                (generate_password_hash("Gestor@2026#"),),
            )

            # Cria um cliente base
            cursor = conn.execute(
                """
                INSERT INTO clientes (nome_empresa, responsavel_nome, responsavel_email, telefone, ativo, criado_em)
                VALUES ('Empresa Teste', 'João Silva', 'joao@empresa.com', '1199999999', 1, '2026-01-01 00:00:00')
                """
            )
            self.cliente_id = cursor.lastrowid

            # Cria uma licença base
            cursor_lic = conn.execute(
                """
                INSERT INTO licencas (cliente_id, chave_licenca, tipo_plano, limite_hosts, limite_agentes, status, data_emissao, data_expiracao)
                VALUES (?, 'TEST-AAAA-BBBB-CCCC', 'Profissional', 10, 5, 'ativa', '2026-01-01 00:00:00', '2026-12-31 23:59:59')
                """,
                (self.cliente_id,),
            )
            self.licenca_id = cursor_lic.lastrowid

        self.app = self.application
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def _get_csrf_token(self):
        with self.client.session_transaction() as sess:
            return sess.get("_csrf_token")

    def _login(self, username, senha):
        self.client.get("/login")
        token = self._get_csrf_token()
        return self.client.post(
            "/login",
            data={"username": username, "senha": senha, "csrf_token": token},
            follow_redirects=True,
        )

    def test_assistente_bloqueado_criar_cliente(self):
        self._login("user.assistente", "Assistente@2026#")

        # GET /clientes/novo deve redirecionar com aviso
        resp_get = self.client.get("/clientes/novo", follow_redirects=True)
        self.assertIn(
            "Usuários com perfil Assistente não têm permissão para cadastrar clientes.".encode(
                "utf-8"
            ),
            resp_get.data,
        )

        # POST /clientes/novo não deve criar cliente
        token = self._get_csrf_token()
        resp_post = self.client.post(
            "/clientes/novo",
            data={
                "nome_empresa": "Tentativa Invasora",
                "responsavel_nome": "Hacker",
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        self.assertIn(
            "Usuários com perfil Assistente não têm permissão para cadastrar clientes.".encode(
                "utf-8"
            ),
            resp_post.data,
        )

        with get_db() as conn:
            cliente = conn.execute(
                "SELECT * FROM clientes WHERE nome_empresa = 'Tentativa Invasora'"
            ).fetchone()
            self.assertIsNone(cliente)

    def test_assistente_bloqueado_excluir_cliente(self):
        self._login("user.assistente", "Assistente@2026#")

        token = self._get_csrf_token()
        resp = self.client.post(
            f"/clientes/{self.cliente_id}/excluir",
            data={"csrf_token": token},
            follow_redirects=True,
        )
        self.assertIn(
            "Usuários com perfil Assistente não têm permissão para excluir clientes.".encode(
                "utf-8"
            ),
            resp.data,
        )

        with get_db() as conn:
            cliente = conn.execute(
                "SELECT * FROM clientes WHERE id = ?", (self.cliente_id,)
            ).fetchone()
            self.assertIsNotNone(cliente)

    def test_assistente_bloqueado_emitir_licenca(self):
        self._login("user.assistente", "Assistente@2026#")

        # GET /licencas/nova deve redirecionar com aviso
        resp_get = self.client.get("/licencas/nova", follow_redirects=True)
        self.assertIn(
            "Usuários com perfil Assistente não têm permissão para emitir licenças.".encode(
                "utf-8"
            ),
            resp_get.data,
        )

        # POST /licencas/nova não deve gerar licença
        token = self._get_csrf_token()
        resp_post = self.client.post(
            "/licencas/nova",
            data={
                "cliente_id": self.cliente_id,
                "tipo_plano": "Enterprise",
                "limite_hosts": 100,
                "limite_agentes": 50,
                "dias_validade": 30,
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        self.assertIn(
            "Usuários com perfil Assistente não têm permissão para emitir licenças.".encode(
                "utf-8"
            ),
            resp_post.data,
        )

        with get_db() as conn:
            lic = conn.execute("SELECT * FROM licencas WHERE tipo_plano = 'Enterprise'").fetchone()
            self.assertIsNone(lic)

    def test_assistente_bloqueado_excluir_licenca(self):
        self._login("user.assistente", "Assistente@2026#")

        token = self._get_csrf_token()
        resp = self.client.post(
            f"/licencas/{self.licenca_id}/excluir",
            data={"csrf_token": token},
            follow_redirects=True,
        )
        self.assertIn(
            "Apenas usuários com perfil Superadmin podem excluir licenças".encode("utf-8"),
            resp.data,
        )

        with get_db() as conn:
            lic = conn.execute("SELECT * FROM licencas WHERE id = ?", (self.licenca_id,)).fetchone()
            self.assertIsNotNone(lic)

    def test_assistente_ui_permissoes_e_botoes(self):
        self.app.config["ALLOW_ASSISTANT_LICENSE_EDITS"] = True
        self._login("user.assistente", "Assistente@2026#")

        # Em /clientes/ não deve haver link para novo nem form de exclusão, mas DEVE haver link para editar
        resp_cli = self.client.get("/clientes/")
        self.assertNotIn(b'href="/clientes/novo"', resp_cli.data)
        self.assertNotIn(
            f'action="/clientes/{self.cliente_id}/excluir"'.encode("utf-8"), resp_cli.data
        )
        self.assertIn(f'href="/clientes/{self.cliente_id}/editar"'.encode("utf-8"), resp_cli.data)

        # Em /licencas/ não deve haver link para nova nem form de exclusão, mas DEVE haver link para editar e detalhes
        resp_lic = self.client.get("/licencas/")
        self.assertNotIn(b'href="/licencas/nova"', resp_lic.data)
        self.assertNotIn(
            f'action="/licencas/{self.licenca_id}/excluir"'.encode("utf-8"), resp_lic.data
        )
        self.assertIn(f'href="/licencas/{self.licenca_id}/editar"'.encode("utf-8"), resp_lic.data)
        self.assertIn(f'href="/licencas/{self.licenca_id}/detalhes"'.encode("utf-8"), resp_lic.data)

        # Em /licencas/<id>/detalhes DEVE haver botão de editar licença, mas NÃO o de excluir
        resp_det = self.client.get(f"/licencas/{self.licenca_id}/detalhes")
        self.assertIn(f'href="/licencas/{self.licenca_id}/editar"'.encode("utf-8"), resp_det.data)
        self.assertNotIn(
            f'action="/licencas/{self.licenca_id}/excluir"'.encode("utf-8"), resp_det.data
        )

        # No Dashboard não deve haver link para licencas/nova
        resp_dash = self.client.get("/")
        self.assertEqual(resp_dash.status_code, 200)
        self.assertNotIn(b'href="/licencas/nova"', resp_dash.data)

    def test_assistente_edicao_cliente_apenas_contato(self):
        self._login("user.assistente", "Assistente@2026#")

        # GET da página de edição deve carregar normalmente e indicar campos restritos
        resp_get = self.client.get(f"/clientes/{self.cliente_id}/editar")
        self.assertEqual(resp_get.status_code, 200)
        self.assertIn("Perfil <strong>Assistente</strong>".encode("utf-8"), resp_get.data)
        self.assertIn(b"disabled", resp_get.data)  # checkbox de ativo desabilitada

        # POST tentando alterar nome, ativo e dados de contato
        token = self._get_csrf_token()
        resp_post = self.client.post(
            f"/clientes/{self.cliente_id}/editar",
            data={
                "nome_empresa": "Nome Modificado Invasor",
                "responsavel_nome": "Responsavel Invasor",
                "responsavel_email": "novo.email@empresa.com",
                "telefone": "(11) 98888-7777",
                "cnpj_cpf": "99.999.999/0001-99",
                "observacoes": "Obs invasora",
                "ativo": "0",  # Tentativa de desativar cliente
                "csrf_token": token,
            },
            follow_redirects=True,
        )

        self.assertIn(
            "Informações de contato do cliente atualizadas com sucesso!".encode("utf-8"),
            resp_post.data,
        )

        # Verifica no banco: SOMENTE e-mail e telefone foram atualizados; nome, responsável e ativo foram preservados!
        with get_db() as conn:
            c = conn.execute("SELECT * FROM clientes WHERE id = ?", (self.cliente_id,)).fetchone()
            self.assertEqual(c["responsavel_email"], "novo.email@empresa.com")
            self.assertEqual(c["telefone"], "(11) 98888-7777")
            self.assertEqual(c["nome_empresa"], "Empresa Teste")
            self.assertEqual(c["responsavel_nome"], "João Silva")
            self.assertEqual(c["ativo"], 1)

    def test_assistente_pode_editar_informacoes_licenca_quando_autorizado(self):
        self.app.config["ALLOW_ASSISTANT_LICENSE_EDITS"] = True
        self._login("user.assistente", "Assistente@2026#")

        # GET na página de edição de licença
        resp_get = self.client.get(f"/licencas/{self.licenca_id}/editar")
        self.assertEqual(resp_get.status_code, 200)

        # POST alterando plano, limites, expiração e status da licença
        token = self._get_csrf_token()
        resp_post = self.client.post(
            f"/licencas/{self.licenca_id}/editar",
            data={
                "tipo_plano": "Enterprise",
                "limite_hosts": 150,
                "limite_agentes": 75,
                "status": "suspensa",
                "data_expiracao": "2027-06-30",
                "observacoes": "Ajuste feito pelo assistente",
                "csrf_token": token,
            },
            follow_redirects=True,
        )

        self.assertIn("Licença atualizada com sucesso!".encode("utf-8"), resp_post.data)

        # Verifica no banco que os dados foram atualizados
        with get_db() as conn:
            lic = conn.execute("SELECT * FROM licencas WHERE id = ?", (self.licenca_id,)).fetchone()
            self.assertEqual(lic["tipo_plano"], "Enterprise")
            self.assertEqual(lic["limite_hosts"], 150)
            self.assertEqual(lic["limite_agentes"], 75)
            self.assertEqual(lic["status"], "suspensa")
            self.assertIn("2027-06-30", lic["data_expiracao"])
            self.assertEqual(lic["observacoes"], "Ajuste feito pelo assistente")

    def test_gestor_pode_criar_cliente_e_emitir_licenca(self):
        self._login("user.gestor", "Gestor@2026#")

        # GET /clientes/novo deve permitir
        resp_cli_get = self.client.get("/clientes/novo")
        self.assertEqual(resp_cli_get.status_code, 200)

        # POST /clientes/novo deve criar cliente
        token = self._get_csrf_token()
        resp_cli_post = self.client.post(
            "/clientes/novo",
            data={
                "nome_empresa": "Cliente Criado por Gestor",
                "responsavel_nome": "Gestor Responsável",
                "responsavel_email": "gestor.cli@teste.com",
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        self.assertIn("Cliente cadastrado com sucesso!".encode("utf-8"), resp_cli_post.data)

        # GET /licencas/nova deve permitir
        resp_lic_get = self.client.get("/licencas/nova")
        self.assertEqual(resp_lic_get.status_code, 200)

        # POST /licencas/nova deve emitir licença
        token = self._get_csrf_token()
        resp_lic_post = self.client.post(
            "/licencas/nova",
            data={
                "cliente_id": self.cliente_id,
                "tipo_plano": "Enterprise",
                "limite_hosts": 50,
                "limite_agentes": 20,
                "dias_validade": 60,
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        self.assertIn("gerada com sucesso!".encode("utf-8"), resp_lic_post.data)


if __name__ == "__main__":
    unittest.main()
