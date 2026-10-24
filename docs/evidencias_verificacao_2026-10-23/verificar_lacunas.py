"""Reproduções isoladas da revisão. Não usa banco, segredo ou endpoint operacional."""

# ruff: noqa: E402
import json
import os
import sys
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT.parent / "GetPing_eth/getping_v0.0.4"
os.environ["GETPING_CLIENT_SOURCE"] = str(CLIENT)
sys.path[:0] = [str(ROOT), str(CLIENT)]
import requests
from getping import create_app
from getping.config import usar_configuracao
from getping.db import conectar
from getping.db.licenses import gerar_assinatura_licenca
from getping.licensing import (
    obter_licenca_local,
    salvar_licenca_local,
    sincronizar_licenca_com_servidor,
    validar_licenca_remota,
    verificar_status_licenca,
)
from getping.monitoring.collector import Coletor
from getping.monitoring.persistence import saude_monitor

from getping_admin.license_protocol import sign_document
from integration_tests.test_protocol_v2 import SignedIntegrationTests


def record(name, **data):
    print(json.dumps(dict(ensaio=name, **data), ensure_ascii=False))


def response(data):
    result = requests.Response()
    result.status_code = 200
    result.headers["content-type"] = "application/json"
    result._content = json.dumps(data).encode()
    return result


def seal(row):
    return gerar_assinatura_licenca(
        row["chave_licenca"],
        row["cliente_nome"],
        row["tipo_plano"],
        row["limite_hosts"],
        row["limite_agentes"],
        row["status"],
        row["expira_em"],
        row["instancia_fingerprint"],
        row["servidor_admin_url"],
        row["ultimo_checkin"],
        row["autorizacao_json"],
        row["revision"],
    )


def run():
    case = SignedIntegrationTests()
    case.setUp()
    try:
        base = dict(case.config)
        # Factory real, sem TESTING, com configuração incompleta.
        try:
            create_app(
                {
                    "GETPING_ENV": "production",
                    "DB_PATH": str(case.root / "missing.db"),
                    "SECRET_KEY": base["SECRET_KEY"],
                    "SESSION_COOKIE_SECURE": True,
                    "LICENCA_SERVER_URL": base["LICENCA_SERVER_URL"],
                    "LICENCA_PUBLIC_KEY_FILE": "",
                }
            )
            blocked = False
        except RuntimeError:
            blocked = True
        record("L1_inicio_sem_chave", bloqueado=blocked)
        assert blocked
        case.authorize(agents=1)
        original = obter_licenca_local()
        # L4: Mesmo com o segredo local, o documento central protege as cotas.
        with conectar() as conn:
            changed = dict(original, limite_agentes=9999)
            conn.execute(
                "UPDATE licenca_local SET limite_agentes=?,assinatura_integridade=?",
                (9999, seal(changed)),
            )
        record("L4_cota_divergente_assinatura_central", valida=verificar_status_licenca()["valida"])
        assert not verificar_status_licenca()["valida"]
        case.authorize(agents=1)
        # Negativa fabricada não possui assinatura ou nonce, mas é aplicada.
        fake = requests.Response()
        fake.status_code = 403
        fake.headers["content-type"] = "application/json"
        fake._content = b'{"valido":false,"status":"cancelada","motivo":"Fixture"}'
        with patch("getping.licensing._http_post", return_value=fake):
            ok, _, data = sincronizar_licenca_com_servidor()
        record(
            "negativa_nao_assinada",
            falha_transporte=data.get("conexao_falhou", False),
            estado_local=obter_licenca_local()["status"],
        )
        assert obter_licenca_local()["status"] == "cancelada"
        # Metadados obrigatórios ausentes, mesmo com assinatura legítima de fixture.
        signer = case.admin.extensions["license_signer"]
        cases = []
        for field in ("chave_licenca", "fingerprint", "emissor"):

            def missing(endpoint, payload, field=field):
                doc = case.bridge(endpoint, payload).json()
                doc.pop(field)
                doc.pop("assinatura")
                return response(sign_document(doc, signer))

            with patch("getping.licensing._http_post", side_effect=missing):
                ok, _, _ = validar_licenca_remota(case.key)
            cases.append({"campo_omitido": field, "aceita": ok})
        record("L5_campos_ausentes", resultados=cases)
        assert all(row["aceita"] for row in cases)

        # Nonce atual não compensa uma assinatura adulterada: deve ser erro controlado.
        def invalid_signature(endpoint, payload):
            doc = case.bridge(endpoint, payload).json()
            doc["limite_hosts"] = 999
            return response(doc)

        with patch("getping.licensing._http_post", side_effect=invalid_signature):
            try:
                validar_licenca_remota(case.key)
                exception = None
            except Exception as error:
                exception = type(error).__name__
        record("assinatura_invalida_tratamento", excecao=exception)
        assert exception == "InvalidSignature"
        # L3: Heartbeat continua, mas é gravado como erro e a prontidão retorna 503.
        case.authorize(agents=1)
        case.update("UPDATE licencas SET status='cancelada' WHERE id=?", (case.lid,))
        sincronizar_licenca_com_servidor()
        collector = Coletor(workers=1, config=case.config)
        try:
            collector.tick()
            health = saude_monitor()
            web = create_app(
                {
                    "TESTING": True,
                    "DB_PATH": str(case.root / "client.db"),
                    "SECRET_KEY": base["SECRET_KEY"],
                }
            )
            result = web.test_client().get("/status_server?ready=1")
            record(
                "L3_heartbeat_e_prontidao",
                ativo=health["ativo"],
                saudavel=health["saudavel"],
                http=result.status_code,
            )
            assert health["ativo"] and not health["saudavel"] and result.status_code == 503
            # Tarefa já iniciada não é encerrada; deixa de ser acompanhada.
            running = Future()
            running.set_running_or_notify_cancel()
            collector.em_voo[running] = ("fixture", [], 0, None)
            collector.tick()
            record(
                "coleta_em_voo_apos_bloqueio",
                future_cancelado=running.cancelled(),
                future_em_execucao=running.running(),
                acompanhado=running in collector.em_voo,
            )
            assert running.running() and running not in collector.em_voo
            running.set_result(None)
        finally:
            collector.close()
        # Formulário de ativação não captura revisão antes da rede.
        case.update("UPDATE licencas SET status='ativa' WHERE id=?", (case.lid,))
        data_a = case.authorize(agents=1)
        other = "GP-FIXTURE-OTHER"
        from getping_admin.database.db import get_db

        with case.admin.app_context(), get_db() as conn:
            lid = conn.execute(
                "INSERT INTO licencas(cliente_id,chave_licenca,data_emissao,data_expiracao) VALUES (?,?,'2026-01-01 00:00:00','2099-01-01 00:00:00')",
                (case.cid, other),
            ).lastrowid
            conn.execute(
                "INSERT INTO license_bindings VALUES (?,?,NULL,datetime('now'))",
                (lid, case.fingerprint),
            )
        payload = dict(
            chave_licenca=other, fingerprint=case.fingerprint, protocolo=2, nonce="b" * 64
        )
        data_b = case.bridge("https://central.example.test", payload).json()
        import hashlib

        from werkzeug.security import generate_password_hash

        password_hash = generate_password_hash("Audit-Only@123")
        with conectar() as conn:
            uid = conn.execute(
                "INSERT INTO usuarios(nome,username,senha_hash,perfil,empresa_id,ativo,criado_em,troca_senha_obrigatoria,token_sessao) VALUES ('Fixture','audit-root',?,'root',1,1,'2026-01-01',0,'audit-token')",
                (password_hash,),
            ).lastrowid
        app = create_app(
            {
                "TESTING": True,
                "DB_PATH": str(case.root / "client.db"),
                "SECRET_KEY": base["SECRET_KEY"],
            }
        )
        client = app.test_client()
        with client.session_transaction() as session:
            session.update(
                usuario_id=uid,
                usuario_perfil="root",
                usuario_nome="Fixture",
                usuario_username="audit-root",
                token_sessao="audit-token",
                auth_hash=hashlib.sha256(password_hash.encode()).hexdigest()[:16],
            )

        def delay_activation(*args, **kwargs):
            salvar_licenca_local(data_b, other, base["LICENCA_SERVER_URL"])
            return True, data_a, "Autorizada"

        with patch("getping.routes.licenca.validar_licenca_remota", side_effect=delay_activation):
            result = client.post("/licenca/ativar", data={"chave_licenca": case.key})
        record(
            "M2_formulario_resposta_antiga",
            http=result.status_code,
            chave_nova_preservada=obter_licenca_local()["chave_licenca"] == other,
        )
        assert result.status_code == 302 and obter_licenca_local()["chave_licenca"] == case.key
        # L6: gravação usa UTC em vez do fuso local do processo.
        case.update("UPDATE licencas SET status='ativa' WHERE id=?", (case.lid,))
        case.authorize(agents=1)
        from getping.license_protocol import utc_now

        local = obter_licenca_local()
        record(
            "L6_checkin_utc",
            checkin_igual_minuto_utc=local["ultimo_checkin"][:16]
            == utc_now().strftime("%Y-%m-%d %H:%M"),
        )
        # UI ainda apresenta zero agentes como ilimitado, embora a regra tenha mudado.
        case.authorize(agents=0)
        page = client.get("/configuracoes")
        text = page.get_data(as_text=True)
        record(
            "zero_agentes_interface", http=page.status_code, mostra_ilimitado="Ilimitado" in text
        )
        assert page.status_code == 200 and "Ilimitado" in text
        # L8: cache anterior não é exibido como adulteração.
        with conectar() as conn:
            conn.execute(
                "UPDATE licenca_local SET assinatura_integridade='legacy',autorizacao_json=NULL,revision=0"
            )
        record("L8_legado", status=verificar_status_licenca()["status"])
        assert verificar_status_licenca()["status"] == "revalidacao_necessaria"
        # L1 positivo incompleto agora é negado fora de development, sem chave.
        no_key = dict(base, LICENCA_PUBLIC_KEY_FILE=None)
        with (
            usar_configuracao(no_key),
            patch(
                "getping.licensing._http_post",
                return_value=response({"valido": True, "limite_agentes": 99999}),
            ),
        ):
            ok, data, _ = validar_licenca_remota(case.key)
        record("L1_positivo_sem_chave", aceita=ok, falha_contrato=data.get("conexao_falhou", False))
        assert not ok
    finally:
        case.doCleanups()


if __name__ == "__main__":
    run()
