"""Regressões das pendências verificadas em 23/10, com a central e o cliente reais."""

import json
import os
import unittest
from concurrent.futures import Future
from unittest.mock import patch

from integration_tests import test_protocol_v2 as fixtures

CLIENT = os.environ.get("GETPING_CLIENT_SOURCE")
if CLIENT:
    import hashlib

    import requests
    from getping import create_app
    from getping.db import conectar
    from getping.licensing import (
        obter_licenca_local,
        salvar_licenca_local,
        sincronizar_licenca_com_servidor,
        validar_licenca_remota,
        verificar_status_licenca,
    )
    from getping.monitoring.collector import Coletor
    from getping.monitoring.persistence import saude_monitor
    from getping.monitoring.policy import Resultado
    from werkzeug.security import generate_password_hash

    from getping_admin.database.db import get_db
    from getping_admin.license_protocol import sign_document, verify_document


@unittest.skipUnless(CLIENT, "Defina GETPING_CLIENT_SOURCE para executar a integração.")
class PendingCorrectionsTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.SignedIntegrationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def response(self, data, code=403):
        result = requests.Response()
        result.status_code = code
        result.headers["content-type"] = "application/json"
        result._content = json.dumps(data).encode()
        return result

    def client(self):
        app = create_app(
            {
                "TESTING": True,
                "DB_PATH": str(self.f.root / "client.db"),
                "SECRET_KEY": self.f.config["SECRET_KEY"],
            }
        )
        return app.test_client()

    def logged_client(self):
        password_hash = generate_password_hash("Fixture-Only@123")
        with conectar() as conn:
            uid = conn.execute(
                "INSERT INTO usuarios(nome,username,senha_hash,perfil,empresa_id,ativo,criado_em,troca_senha_obrigatoria,token_sessao) VALUES ('Fixture','fixture-root',?,'root',1,1,'2026-01-01',0,'fixture-token')",
                (password_hash,),
            ).lastrowid
        client = self.client()
        with client.session_transaction(base_url="https://getping.example.test") as session:
            session.update(
                usuario_id=uid,
                usuario_perfil="root",
                usuario_nome="Fixture",
                usuario_username="fixture-root",
                token_sessao="fixture-token",
                auth_hash=hashlib.sha256(password_hash.encode()).hexdigest()[:16],
            )
        return client

    def test_unsigned_negative_does_not_cancel_or_renew(self):
        self.f.authorize()
        before = obter_licenca_local()
        for status in (
            "cancelada",
            "suspensa",
            "aguardando_vinculo",
            "instancia_invalida",
            "invalida",
        ):
            with (
                self.subTest(status=status),
                patch(
                    "getping.licensing._http_post",
                    return_value=self.response({"valido": False, "status": status}),
                ),
            ):
                ok, _, data = sincronizar_licenca_com_servidor()
                self.assertFalse(ok)
                self.assertTrue(data["conexao_falhou"])
                self.assertEqual(obter_licenca_local(), before)
                self.assertTrue(verificar_status_licenca()["valida"])

    def test_missing_bindings_rejected_in_positive_and_negative_documents(self):
        self.f.authorize()
        for state in ("ativa", "cancelada"):
            self.f.update("UPDATE licencas SET status=? WHERE id=?", (state, self.f.lid))
            for field in (
                "chave_licenca",
                "fingerprint",
                "emissor",
                "nonce",
                "emitido_em_iso",
                "offline_ate_iso",
            ):

                def altered(endpoint, payload, omitted=field):
                    doc = self.f.bridge(endpoint, payload).json()
                    doc.pop(omitted)
                    return self.response(
                        sign_document(doc, self.f.admin.extensions["license_signer"]),
                        200 if state == "ativa" else 403,
                    )

                with (
                    self.subTest(state=state, field=field),
                    patch("getping.licensing._http_post", side_effect=altered),
                ):
                    ok, data, _ = validar_licenca_remota(self.f.key)
                    self.assertFalse(ok)
                    self.assertTrue(data["conexao_falhou"])

    def test_invalid_signature_with_current_nonce_is_controlled(self):
        self.f.authorize()
        before = obter_licenca_local()
        for state in ("ativa", "cancelada"):
            self.f.update("UPDATE licencas SET status=? WHERE id=?", (state, self.f.lid))

            def corrupt(endpoint, payload):
                doc = self.f.bridge(endpoint, payload).json()
                doc["mensagem"] = "Corrupted fixture"
                return self.response(doc, 200 if state == "ativa" else 403)

            with (
                self.subTest(state=state),
                patch("getping.licensing._http_post", side_effect=corrupt),
            ):
                ok, _, data = sincronizar_licenca_com_servidor()
                self.assertFalse(ok)
                self.assertTrue(data["conexao_falhou"])
                self.assertEqual(obter_licenca_local(), before)

    def test_pending_document_is_preserved_and_signature_remains_valid(self):
        ok, doc, _ = validar_licenca_remota(self.f.key)
        self.assertFalse(ok)
        original = dict(doc)
        self.assertTrue(salvar_licenca_local(doc, self.f.key, self.f.config["LICENCA_SERVER_URL"]))
        self.assertEqual(doc, original)
        stored = json.loads(obter_licenca_local()["autorizacao_json"])
        self.assertEqual(stored, original)
        verify_document(stored, self.f.admin.extensions["license_signer"].public_key())
        self.assertEqual(verificar_status_licenca()["status"], "aguardando_vinculo")

    def test_unsigned_status_cannot_be_written_directly_in_production(self):
        from getping.licensing import atualizar_status_licenca_local

        self.f.authorize()
        before = obter_licenca_local()
        with self.assertRaises(ValueError):
            atualizar_status_licenca_local("cancelada", "Not signed")
        self.assertEqual(obter_licenca_local(), before)
        with self.assertRaises(ValueError):
            salvar_licenca_local(
                {"valido": False, "status": "cancelada"},
                self.f.key,
                self.f.config["LICENCA_SERVER_URL"],
            )

    def test_active_service_without_license_is_ready_but_collection_is_blocked(self):
        collector = Coletor(workers=1, config=self.f.config)
        try:
            collector.tick()
            self.assertTrue(saude_monitor()["ativo"])
            self.assertTrue(saude_monitor()["saudavel"])
            response = self.client().get(
                "/status_server?ready=1", base_url="https://getping.example.test"
            )
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json["coleta_autorizada"])
            self.assertEqual(response.json["status_licenca"], "inexistente")
            self.f.authorize()
            self.f.update("UPDATE licencas SET status='cancelada' WHERE id=?", (self.f.lid,))
            sincronizar_licenca_com_servidor()
            collector.ultimo_heartbeat = 0
            collector.tick()
            self.assertTrue(saude_monitor()["saudavel"])
            self.assertFalse(verificar_status_licenca()["valida"])
        finally:
            collector.close()

    def test_running_probe_keeps_slot_and_discards_result_after_reactivation(self):
        self.f.authorize()
        collector = Coletor(workers=1, config=self.f.config)
        running = Future()
        running.set_running_or_notify_cancel()
        collector.em_voo[running] = ("fixture", [], 0, None)
        queued = Future()
        collector.em_voo[queued] = ("queued", [], 0, None)
        try:
            self.f.update("UPDATE licencas SET status='cancelada' WHERE id=?", (self.f.lid,))
            sincronizar_licenca_com_servidor()
            collector.tick()
            self.assertTrue(queued.cancelled())
            self.assertNotIn(queued, collector.em_voo)
            self.assertIn(running, collector.em_voo)
            self.assertIn(running, collector.descartar)
            self.f.update("UPDATE licencas SET status='ativa' WHERE id=?", (self.f.lid,))
            sincronizar_licenca_com_servidor()
            running.set_result(Resultado("SUCESSO"))
            with patch("getping.monitoring.collector.aplicar_lote_resultados") as persist:
                collector.tick()
                persist.assert_not_called()
            self.assertNotIn(running, collector.em_voo)
            self.assertNotIn(running, collector.descartar)
            self.assertNotIn("licenca", collector.erros)
        finally:
            if not running.done():
                running.set_result(None)
            collector.close()

    def test_old_activation_response_cannot_overwrite_new_key(self):
        old = self.f.authorize()
        other = "GP-FIXTURE-OTHER"
        with self.f.admin.app_context(), get_db() as conn:
            lid = conn.execute(
                "INSERT INTO licencas(cliente_id,chave_licenca,data_emissao,data_expiracao) VALUES (?,?,'2026-01-01 00:00:00','2099-01-01 00:00:00')",
                (self.f.cid, other),
            ).lastrowid
            conn.execute(
                "INSERT INTO license_bindings VALUES (?,?,NULL,datetime('now'))",
                (lid, self.f.fingerprint),
            )
        new = self.f.bridge(
            "fixture",
            dict(chave_licenca=other, fingerprint=self.f.fingerprint, protocolo=2, nonce="a" * 64),
        ).json()
        client = self.logged_client()

        def delay(*args):
            salvar_licenca_local(new, other, self.f.config["LICENCA_SERVER_URL"])
            return True, old, "Old response"

        with patch("getping.routes.licenca.validar_licenca_remota", side_effect=delay):
            response = client.post(
                "/licenca/ativar",
                data={"chave_licenca": self.f.key},
                base_url="https://getping.example.test",
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(obter_licenca_local()["chave_licenca"], other)
        self.assertTrue(verificar_status_licenca()["valida"])

    def test_old_pending_response_does_not_revoke_new_authorization(self):
        _, pending, _ = validar_licenca_remota(self.f.key)
        salvar_licenca_local(pending, self.f.key, self.f.config["LICENCA_SERVER_URL"])
        client = self.logged_client()

        def delay(*args):
            self.f.authorize()
            return False, pending, "Pending"

        with patch("getping.routes.licenca.validar_licenca_remota", side_effect=delay):
            client.post(
                "/licenca/ativar",
                data={"chave_licenca": self.f.key},
                base_url="https://getping.example.test",
            )
        self.assertTrue(verificar_status_licenca()["valida"])

    def test_ui_zero_agents_is_never_unlimited(self):
        self.f.authorize(agents=0)
        response = self.logged_client().get(
            "/configuracoes", base_url="https://getping.example.test"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("0 (nenhum)", response.get_data(as_text=True))
        self.assertNotIn("Ilimitado", response.get_data(as_text=True))
