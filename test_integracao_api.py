import unittest
from tests.support import IsolatedDatabaseTestCase
from app import create_app
from database.db import get_db

class TestApiValidacaoCompleta(IsolatedDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.application
        self.client = self.app.test_client()
        with get_db() as conn:
            conn.execute("DELETE FROM licencas WHERE chave_licenca IN ('GPING-SUSP-1111-2222-3333', 'GPING-VENC-9999-8888-7777')")
            conn.execute("DELETE FROM clientes WHERE nome_empresa IN ('Empresa Suspensao', 'Empresa Expirada')")

    def test_suspensao_cliente_e_licenca(self):
        # Cria cliente e licenca diretamente
        with get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO clientes (nome_empresa, responsavel_nome, ativo, criado_em) VALUES ('Empresa Suspensao', 'Resp', 1, '2026-01-01 00:00:00')"
            )
            cliente_id = cursor.lastrowid
            conn.execute(
                """
                INSERT INTO licencas (cliente_id, chave_licenca, tipo_plano, limite_hosts, limite_agentes, status, data_emissao, data_expiracao)
                VALUES (?, 'GPING-SUSP-1111-2222-3333', 'Basico', 10, 5, 'suspensa', '2026-01-01 00:00:00', '2027-01-01 00:00:00')
                """,
                (cliente_id,)
            )

        # 1. Testar consulta de licença com status suspensa
        resp = self.client.post("/api/v1/licenca/validar", json={"chave_licenca": "GPING-SUSP-1111-2222-3333"})
        self.assertEqual(resp.status_code, 403)
        self.assertIn("suspensa", resp.get_json()["motivo"])

        # 2. Ativar licença mas inativar o cliente
        with get_db() as conn:
            conn.execute("UPDATE licencas SET status = 'ativa' WHERE chave_licenca = 'GPING-SUSP-1111-2222-3333'")
            conn.execute("UPDATE clientes SET ativo = 0 WHERE id = ?", (cliente_id,))

        resp2 = self.client.post("/api/v1/licenca/validar", json={"chave_licenca": "GPING-SUSP-1111-2222-3333"})
        self.assertEqual(resp2.status_code, 403)
        self.assertIn("cliente está suspensa/inativa", resp2.get_json()["motivo"])

    def test_licenca_expirada(self):
        with get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO clientes (nome_empresa, responsavel_nome, ativo, criado_em) VALUES ('Empresa Expirada', 'Resp', 1, '2026-01-01 00:00:00')"
            )
            cliente_id = cursor.lastrowid
            conn.execute(
                """
                INSERT INTO licencas (cliente_id, chave_licenca, tipo_plano, limite_hosts, limite_agentes, status, data_emissao, data_expiracao)
                VALUES (?, 'GPING-VENC-9999-8888-7777', 'Basico', 10, 5, 'ativa', '2025-01-01 00:00:00', '2025-02-01 00:00:00')
                """,
                (cliente_id,)
            )

        resp = self.client.post("/api/v1/licenca/validar", json={"chave_licenca": "GPING-VENC-9999-8888-7777"})
        self.assertEqual(resp.status_code, 403)
        self.assertIn("expirada", resp.get_json()["motivo"])

if __name__ == "__main__":
    unittest.main()
