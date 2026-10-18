"""A validação explícita das views deve anteceder qualquer alteração persistida."""

from getping_admin.database.db import get_db
from tests.support import IsolatedDatabaseTestCase


class FormValidationTests(IsolatedDatabaseTestCase):
    def test_invalid_customer_form_does_not_persist(self):
        self.authenticate(1)
        for fields in (
            {"responsavel_email": "invalid"},
            {"nome_empresa": "X" * 201},
            {"observacoes": "X" * 4001},
        ):
            with self.subTest(fields=list(fields)):
                response = self.client.post(
                    "/clientes/novo",
                    data={
                        "csrf_token": "test-csrf",
                        "nome_empresa": "Empresa",
                        "responsavel_nome": "Responsável",
                        **fields,
                    },
                )
                self.assertEqual(response.status_code, 400)
        with get_db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM admin_audit").fetchone()[0], 0)

    def test_profile_validation_rejects_oversized_password_before_update(self):
        self.authenticate(1)
        response = self.client.post(
            "/perfil",
            data={
                "csrf_token": "test-csrf",
                "nome": "Changed",
                "email": "changed@example.com",
                "senha_atual": "SenhaForte@123",
                "nova_senha": "X" * 257,
            },
        )
        self.assertEqual(response.status_code, 400)
        with get_db() as conn:
            user = conn.execute(
                "SELECT nome, auth_version FROM admin_usuarios WHERE id=1"
            ).fetchone()
            self.assertEqual(user["nome"], "Admin Teste")
            self.assertEqual(user["auth_version"], 0)
