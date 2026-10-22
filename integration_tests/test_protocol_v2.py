"""Contrato real de produção, com bancos/chaves temporários e ambos os projetos."""

import importlib
import json
import os
import secrets
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

CLIENT = os.environ.get("GETPING_CLIENT_SOURCE")
if CLIENT:
    sys.path.insert(0, CLIENT)
    import requests
    from getping import create_app as client_factory
    from getping.config import carregar_opcoes, usar_configuracao
    from getping.db import conectar
    from getping.db.agents import criar_token
    from getping.db.schema import criar_db
    from getping.license_protocol import utc_now
    from getping.licensing import (
        arquivo_fingerprint,
        obter_fingerprint_servidor,
        obter_licenca_local,
        salvar_licenca_local,
        sincronizar_licenca_com_servidor,
        validar_licenca_remota,
        verificar_status_licenca,
    )

    from getping_admin import create_app
    from getping_admin.database.db import get_db
    from getping_admin.license_keys import generate
    from getping_admin.license_protocol import sign_document


@unittest.skipUnless(
    CLIENT, "Defina GETPING_CLIENT_SOURCE para executar a integração entre projetos."
)
class SignedIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="getping-signed-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        private, public = self.root / "private.pem", self.root / "public.pem"
        generate(private, public)
        # Não carrega .env operacional ao construir o cliente.
        env_file = self.root / "empty.env"
        env_file.write_text("")
        env = patch.dict(
            os.environ,
            {
                "GETPING_ENV": "production",
                "GETPING_CONFIG_FILE": str(env_file),
                "LICENCA_SERVER_URL": "https://central.example.test",
                "LICENCA_PUBLIC_KEY_FILE": str(public),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.config = carregar_opcoes(
            {"DB_PATH": str(self.root / "client.db"), "SECRET_KEY": secrets.token_hex(32)}
        )
        context = usar_configuracao(self.config)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        criar_db()
        self.fingerprint = obter_fingerprint_servidor()
        self.admin = create_app(
            {
                "TESTING": True,
                "DATABASE": str(self.root / "admin.db"),
                "SECRET_KEY": secrets.token_hex(32),
                "INIT_DB": True,
                "ENVIRONMENT": "production",
                "PUBLIC_BASE_URL": "https://central.example.test",
                "REQUIRE_HTTPS": True,
                "REQUIRE_FINGERPRINT": True,
                "LICENSE_SIGNING_KEY_FILE": str(private),
                "API_RATE_LIMIT": 0,
            }
        )
        self.central = self.admin.test_client()
        self.key = "GP-FIXTURE-ONLY"
        self.expiration = utc_now() + timedelta(days=30)
        with self.admin.app_context(), get_db() as conn:
            cid = conn.execute(
                "INSERT INTO clientes(nome_empresa,responsavel_nome,criado_em) VALUES ('Fixture','Fixture','2026-01-01')"
            ).lastrowid
            self.cid = cid
            self.lid = conn.execute(
                "INSERT INTO licencas(cliente_id,chave_licenca,limite_hosts,limite_agentes,data_emissao,data_expiracao) VALUES (?,?,10,0,'2026-01-01 00:00:00',?)",
                (cid, self.key, self.expiration.strftime("%Y-%m-%d %H:%M:%S")),
            ).lastrowid
            conn.execute(
                "INSERT INTO license_bindings VALUES (?,NULL,NULL,datetime('now'))", (self.lid,)
            )
        bridge = patch("getping.licensing._http_post", side_effect=self.bridge)
        bridge.start()
        self.addCleanup(bridge.stop)

    def update(self, sql, params=()):
        with self.admin.app_context(), get_db() as conn:
            conn.execute(sql, params)

    def bridge(self, endpoint, payload):
        self.last_payload = dict(payload)
        response = self.central.post(
            "/api/v1/licenca/validar", base_url="https://central.example.test", json=payload
        )
        result = requests.Response()
        result.status_code = response.status_code
        result.headers.update(response.headers)
        result._content = response.data
        return result

    def authorize(self, agents=0):
        self.update(
            "UPDATE license_bindings SET fingerprint=? WHERE licenca_id=?",
            (self.fingerprint, self.lid),
        )
        self.update("UPDATE licencas SET limite_agentes=? WHERE id=?", (agents, self.lid))
        ok, data, _ = validar_licenca_remota(self.key)
        self.assertTrue(ok)
        salvar_licenca_local(data, self.key, self.config["LICENCA_SERVER_URL"])
        self.assertTrue(verificar_status_licenca()["valida"])
        return data

    def test_protocol_sources_identical(self):
        from getping import license_protocol as client

        from getping_admin import license_protocol as server

        self.assertEqual(Path(client.__file__).read_bytes(), Path(server.__file__).read_bytes())

    def test_pending_authorization_and_transfer_are_authoritative(self):
        ok, data, _ = validar_licenca_remota(self.key)
        self.assertFalse(ok)
        self.assertEqual(data["status"], "aguardando_vinculo")
        salvar_licenca_local(data, self.key, self.config["LICENCA_SERVER_URL"])
        self.assertFalse(verificar_status_licenca()["valida"])
        self.authorize()
        self.update(
            "UPDATE license_bindings SET fingerprint=? WHERE licenca_id=?", ("OTHER", self.lid)
        )
        ok, _, data = sincronizar_licenca_com_servidor()
        self.assertFalse(ok)
        self.assertNotIn("conexao_falhou", data)
        self.assertEqual(verificar_status_licenca()["status"], "instancia_invalida")

    def test_revocation_and_temporary_outage(self):
        self.authorize()
        before = obter_licenca_local()
        with patch("getping.licensing._http_post", side_effect=requests.ConnectionError("offline")):
            sincronizar_licenca_com_servidor()
        self.assertEqual(obter_licenca_local(), before)
        self.assertTrue(verificar_status_licenca()["valida"])
        for status in ("suspensa", "cancelada", "expirada"):
            self.update("UPDATE licencas SET status=? WHERE id=?", (status, self.lid))
            sincronizar_licenca_com_servidor()
            self.assertEqual(verificar_status_licenca()["status"], status)
            self.assertFalse(verificar_status_licenca()["valida"])

    def test_zero_and_revocation_block_existing_agent(self):
        self.authorize(agents=1)
        raw = {
            "DB_PATH": str(self.root / "client.db"),
            "SECRET_KEY": self.config["SECRET_KEY"],
            "TESTING": True,
        }
        app = client_factory(raw)
        client = app.test_client()
        token = criar_token("Fixture")
        payload = {"hostname": "Fixture", "machine_uuid": "FIXTURE", "status_lan": True}

        def submit():
            return client.post(
                "/informacoes_agent",
                base_url="https://getping.example.test",
                json=payload,
                headers={"Authorization": "Bearer " + token},
            )

        self.assertEqual(submit().status_code, 200)
        self.update("UPDATE licencas SET limite_agentes=0 WHERE id=?", (self.lid,))
        sincronizar_licenca_com_servidor()
        self.assertEqual(submit().status_code, 403)
        self.update("UPDATE licencas SET status='cancelada' WHERE id=?", (self.lid,))
        sincronizar_licenca_com_servidor()
        self.assertEqual(submit().status_code, 403)

    def test_cache_metadata_and_fingerprint_tampering_fail_closed(self):
        for column, value in (
            ("ultimo_checkin", "2099-01-01 00:00:00"),
            ("servidor_admin_url", "https://evil.test"),
            ("limite_hosts", 9999),
        ):
            self.authorize()
            with conectar() as conn:
                conn.execute(f"UPDATE licenca_local SET {column}=?", (value,))
            self.assertFalse(verificar_status_licenca()["valida"])
        self.authorize()
        arquivo_fingerprint().write_text("OTHER")
        self.assertFalse(verificar_status_licenca()["valida"])

    def test_signed_expiration_and_offline_boundary_are_utc(self):
        doc = self.authorize()
        until = importlib.import_module("getping.license_protocol").parse_utc(
            doc["offline_ate_iso"]
        )
        with patch("getping.licensing.utc_now", return_value=until):
            self.assertEqual(verificar_status_licenca()["status"], "offline_expirado")
        with patch("getping.licensing.utc_now", return_value=self.expiration):
            self.assertEqual(verificar_status_licenca()["status"], "expirada")

    def test_replay_altered_and_incomplete_documents_do_not_renew(self):
        valid = self.authorize()
        before = obter_licenca_local()
        for altered in (dict(valid, limite_hosts=999), {"valido": True}, valid):
            response = requests.Response()
            response.status_code = 200
            response.headers["content-type"] = "application/json"
            response._content = json.dumps(altered).encode()
            with patch("getping.licensing._http_post", return_value=response):
                ok, _, data = sincronizar_licenca_com_servidor()
            self.assertFalse(ok)
            self.assertTrue(data["conexao_falhou"])
            self.assertEqual(obter_licenca_local(), before)
        # Assinatura correta não dispensa schema obrigatório.
        bad = dict(valid)
        bad.pop("cliente")
        bad.pop("assinatura")
        bad = sign_document(bad, self.admin.extensions["license_signer"])
        with self.assertRaises(ValueError):
            salvar_licenca_local(bad, self.key, self.config["LICENCA_SERVER_URL"])

    def test_old_negative_response_does_not_cancel_new_license(self):
        self.authorize()
        second = "GP-FIXTURE-SECOND"
        with self.admin.app_context(), get_db() as conn:
            lid = conn.execute(
                "INSERT INTO licencas(cliente_id,chave_licenca,data_emissao,data_expiracao) VALUES (?,?,'2026-01-01 00:00:00',?)",
                (self.cid, second, self.expiration.strftime("%Y-%m-%d %H:%M:%S")),
            ).lastrowid
            conn.execute(
                "INSERT INTO license_bindings VALUES (?,?,NULL,datetime('now'))",
                (lid, self.fingerprint),
            )
        self.update("UPDATE licencas SET status='cancelada' WHERE id=?", (self.lid,))

        def delay(endpoint, payload):
            old = self.bridge(endpoint, payload)
            new = self.bridge(endpoint, dict(payload, chave_licenca=second))
            salvar_licenca_local(new.json(), second, self.config["LICENCA_SERVER_URL"])
            return old

        with patch("getping.licensing._http_post", side_effect=delay):
            ok, _, result = sincronizar_licenca_com_servidor()
        self.assertFalse(ok)
        self.assertTrue(result["obsoleta"])
        self.assertEqual(obter_licenca_local()["chave_licenca"], second)
        self.assertTrue(verificar_status_licenca()["valida"])

    def test_production_rejects_http_and_different_authority_before_network(self):
        for url in (
            "http://central.example.test",
            "https://evil.test",
            "https://central.example.test@evil.test",
            "https://central.example.test/path",
        ):
            with patch("getping.licensing._http_post") as network:
                ok, data, _ = validar_licenca_remota(self.key, url)
                self.assertFalse(ok)
                self.assertTrue(data["conexao_falhou"])
                network.assert_not_called()

    def test_foreign_public_key_cannot_issue_authorization(self):
        doc = self.authorize()
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        doc.pop("assinatura")
        doc = sign_document(doc, Ed25519PrivateKey.generate())
        with self.assertRaises(ValueError):
            salvar_licenca_local(doc, self.key, self.config["LICENCA_SERVER_URL"])

    def test_hmac_canonical_fields_cannot_be_redistributed(self):
        self.authorize()
        with conectar() as conn:
            conn.execute(
                "UPDATE licenca_local SET cliente_nome='Fixture|Basico',tipo_plano='Other'"
            )
        self.assertFalse(verificar_status_licenca()["valida"])

    def test_revocation_blocks_manual_collection_and_persistence(self):
        self.authorize(agents=1)
        from getping.db.hosts import buscar_host_por_id, cadastrar_host_manual, toggle_monitoramento
        from getping.monitoring.collector import Coletor
        from getping.monitoring.persistence import aplicar_resultado
        from getping.monitoring.policy import Resultado

        hid = cadastrar_host_manual("Fixture", "127.0.0.1")
        toggle_monitoramento(hid)
        saved = buscar_host_por_id(hid)
        self.update("UPDATE licencas SET status='cancelada' WHERE id=?", (self.lid,))
        sincronizar_licenca_com_servidor()
        self.assertEqual(aplicar_resultado([saved], Resultado("SUCESSO")), [])
        with conectar() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM historico_pings").fetchone()[0], 0)
        collector = Coletor(workers=1, config=self.config)
        try:
            with patch.object(collector, "_sondar") as probe:
                collector.tick()
                probe.assert_not_called()
                self.assertEqual(collector.em_voo, {})
        finally:
            collector.close()

    def test_login_has_source_limits_without_global_account_lockout(self):
        self.authorize()
        from getping.security import verificar_bloqueio_login
        from werkzeug.security import generate_password_hash

        with conectar() as conn:
            conn.execute(
                "INSERT INTO usuarios(nome,username,senha_hash,perfil,empresa_id,ativo,criado_em,troca_senha_obrigatoria) VALUES ('Fixture','root',?,'root',1,1,'2026-01-01',0)",
                (generate_password_hash("Fixture-Senha@123"),),
            )
        app = client_factory(
            {
                "DB_PATH": str(self.root / "client.db"),
                "SECRET_KEY": self.config["SECRET_KEY"],
                "TESTING": True,
                "WTF_CSRF_ENABLED": True,
            }
        )
        for source in range(3):
            client = app.test_client()
            client.get("/login", base_url="https://getping.example.test")
            with client.session_transaction(base_url="https://getping.example.test") as session:
                token = session["_csrf_token"]
            for attempt in range(5):
                client.post(
                    "/login",
                    base_url="https://getping.example.test",
                    data={"username": "root", "senha": "wrong", "csrf_token": token},
                    environ_base={"REMOTE_ADDR": f"198.51.100.{source + 1}"},
                )
        client = app.test_client()
        client.get("/login", base_url="https://getping.example.test")
        with client.session_transaction(base_url="https://getping.example.test") as session:
            token = session["_csrf_token"]
        response = client.post(
            "/login",
            base_url="https://getping.example.test",
            data={"username": "root", "senha": "Fixture-Senha@123", "csrf_token": token},
            environ_base={"REMOTE_ADDR": "198.51.100.99"},
        )
        self.assertEqual(response.status_code, 302)
        with client.session_transaction(base_url="https://getping.example.test") as session:
            self.assertIn("usuario_id", session)
        with app.app_context():
            self.assertTrue(verificar_bloqueio_login("198.51.100.1_root", username="root")[0])

    def test_legacy_cache_requires_revalidation_without_resetting_identity(self):
        self.authorize()
        identity = arquivo_fingerprint().read_bytes()
        with conectar() as conn:
            conn.execute(
                "UPDATE licenca_local SET assinatura_integridade='legacy-v1',autorizacao_json=NULL"
            )
        self.assertFalse(verificar_status_licenca()["valida"])
        criar_db()
        self.assertEqual(arquivo_fingerprint().read_bytes(), identity)
        self.assertTrue(sincronizar_licenca_com_servidor()[0])
        self.assertTrue(verificar_status_licenca()["valida"])


if __name__ == "__main__":
    unittest.main()
