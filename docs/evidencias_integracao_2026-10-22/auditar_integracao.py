"""Ensaios isolados do contrato real: nenhum banco/endpoint operacional é usado."""
# ruff: noqa: E402

import json
import os
import secrets
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

CLIENT_SOURCE = Path(__file__).resolve().parents[3] / "GetPing_eth/getping_v0.0.4"
ADMIN_SOURCE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(CLIENT_SOURCE), str(ADMIN_SOURCE)]
import requests
from getping.config import carregar_opcoes, usar_configuracao
from getping.db import conectar
from getping.db.licenses import validar_assinatura_licenca
from getping.db.schema import criar_db
from getping.licensing import (
    obter_fingerprint_servidor,
    obter_licenca_local,
    salvar_licenca_local,
    sincronizar_licenca_com_servidor,
    validar_licenca_remota,
    verificar_status_licenca,
)

from getping_admin import create_app as create_admin
from getping_admin.database.db import get_db


def record(name, **fields):
    print(json.dumps({"ensaio": name, **fields}, ensure_ascii=False))


def run():
    os.environ["TZ"] = "America/Sao_Paulo"
    time.tzset()
    with tempfile.TemporaryDirectory(prefix="getping-integration-audit-") as directory:
        root = Path(directory)
        os.environ["GETPING_CONFIG_FILE"] = str(root / "empty.env")
        (root / "empty.env").write_text("")
        config = carregar_opcoes(
            {
                "DB_PATH": str(root / "client.db"),
                "SECRET_KEY": secrets.token_hex(32),
                "LICENCA_SERVER_URL": "https://fixture.invalid",
            }
        )
        admin = create_admin(
            {
                "TESTING": True,
                "DATABASE": str(root / "admin.db"),
                "SECRET_KEY": secrets.token_hex(32),
                "INIT_DB": True,
                "REQUIRE_HTTPS": True,
                "PUBLIC_BASE_URL": "https://fixture.invalid",
                "API_RATE_LIMIT": 0,
                "REQUIRE_FINGERPRINT": True,
            }
        )
        central = admin.test_client()
        key = "FIXTURE-ONLY-KEY"
        expiry = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        with admin.app_context(), get_db() as conn:
            cid = conn.execute(
                "INSERT INTO clientes(nome_empresa,responsavel_nome,criado_em) VALUES ('Fixture','Fixture','2026-01-01')"
            ).lastrowid
            lid = conn.execute(
                "INSERT INTO licencas(cliente_id,chave_licenca,limite_agentes,data_emissao,data_expiracao) VALUES (?,?,0,'2026-01-01 00:00:00',?)",
                (cid, key, expiry),
            ).lastrowid
            conn.execute(
                "INSERT INTO license_bindings VALUES (?,NULL,NULL,datetime('now'))", (lid,)
            )

        def bridge(endpoint, payload):
            response = central.post(
                "/api/v1/licenca/validar", base_url="https://fixture.invalid", json=payload
            )
            result = requests.Response()
            result.status_code = response.status_code
            result.headers.update(response.headers)
            result._content = response.data
            return result

        def admin_update(sql, args=()):
            with admin.app_context(), get_db() as conn:
                conn.execute(sql, args)

        with usar_configuracao(config):
            criar_db()
            fingerprint = obter_fingerprint_servidor()
            with patch("getping.licensing._http_post", side_effect=bridge):
                ok, data, _ = validar_licenca_remota(key)
                assert not ok and data["status"] == "aguardando_vinculo"
                salvar_licenca_local(data, key, "https://fixture.invalid")
                record(
                    "pendente",
                    status=verificar_status_licenca()["status"],
                    valida=verificar_status_licenca()["valida"],
                )
                admin_update(
                    "UPDATE license_bindings SET fingerprint=? WHERE licenca_id=?",
                    (fingerprint, lid),
                )
                ok, _, data = sincronizar_licenca_com_servidor()
                assert ok and verificar_status_licenca()["valida"]
                record("autorizada", valida=True, limite_agentes=data["limite_agentes"])
                from getping import create_app

                client_app = create_app(
                    {
                        "DB_PATH": str(root / "client.db"),
                        "SECRET_KEY": config["SECRET_KEY"],
                        "LICENCA_SERVER_URL": "https://fixture.invalid",
                        "TESTING": True,
                    }
                )
                from getping.db.agents import criar_token

                token = criar_token("Audit isolated")
                response = client_app.test_client().post(
                    "/informacoes_agent",
                    json={"hostname": "Fixture", "machine_uuid": "AUDIT-ZERO", "status_lan": True},
                    headers={"Authorization": "Bearer " + token},
                )
                with conectar() as conn:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM hosts WHERE tipo_host='agent'"
                    ).fetchone()[0]
                record("zero_agentes", http=response.status_code, agentes_cadastrados=count)
                assert response.status_code == 200 and count == 1
                admin_update(
                    "UPDATE license_bindings SET fingerprint=? WHERE licenca_id=?",
                    ("OTHER-INSTALLATION", lid),
                )
                denial = central.post(
                    "/api/v1/licenca/validar",
                    base_url="https://fixture.invalid",
                    json={"chave_licenca": key, "fingerprint": fingerprint},
                )
                ok, _, data = sincronizar_licenca_com_servidor()
                record(
                    "vinculo_trocado",
                    servidor_status=denial.json["status"],
                    tratado_como_rede=data.get("conexao_falhou", False),
                    cliente_valida=verificar_status_licenca()["valida"],
                )
                assert (
                    denial.json["status"] == "instancia_invalida"
                    and data["conexao_falhou"]
                    and verificar_status_licenca()["valida"]
                )
                admin_update(
                    "UPDATE license_bindings SET fingerprint=? WHERE licenca_id=?",
                    (fingerprint, lid),
                )
                for state in ("suspensa", "cancelada"):
                    admin_update("UPDATE licencas SET status=? WHERE id=?", (state, lid))
                    sincronizar_licenca_com_servidor()
                    record(
                        state,
                        cliente_status=verificar_status_licenca()["status"],
                        valida=verificar_status_licenca()["valida"],
                    )
                    assert (
                        verificar_status_licenca()["status"] == state
                        and not verificar_status_licenca()["valida"]
                    )
                    admin_update("UPDATE licencas SET status='ativa' WHERE id=?", (lid,))
                    sincronizar_licenca_com_servidor()
                # Cache obtido anteriormente: a validade UTC venceu há uma hora.
                expired = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                old_data = (
                    dict(data)
                    if "limite_hosts" in data
                    else {
                        "valido": True,
                        "cliente": "Fixture",
                        "tipo_plano": "Basico",
                        "limite_hosts": 10,
                        "limite_agentes": 0,
                    }
                )
                old_data.update(valido=True, expira_em=expired)
                old_data.pop("conexao_falhou", None)
                salvar_licenca_local(old_data, key, "https://fixture.invalid")
                admin_update("UPDATE licencas SET data_expiracao=? WHERE id=?", (expired, lid))
                negative = central.post(
                    "/api/v1/licenca/validar",
                    base_url="https://fixture.invalid",
                    json={"chave_licenca": key, "fingerprint": fingerprint},
                )
                record(
                    "vencimento_utc",
                    servidor_status=negative.json["status"],
                    cache_cliente_valida=verificar_status_licenca()["valida"],
                )
                assert (
                    negative.json["status"] == "expirada" and verificar_status_licenca()["valida"]
                )
                admin_update("UPDATE licencas SET data_expiracao=? WHERE id=?", (expiry, lid))
                sincronizar_licenca_com_servidor()
            # Campos locais fora do HMAC; nenhum segredo da instalação é obtido.
            with conectar() as conn:
                conn.execute(
                    "UPDATE licenca_local SET ultimo_checkin=?",
                    ((datetime.now() - timedelta(days=9)).strftime("%Y-%m-%d %H:%M:%S"),),
                )
            assert verificar_status_licenca()["status"] == "offline_expirado"
            with conectar() as conn:
                conn.execute(
                    "UPDATE licenca_local SET ultimo_checkin=?",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),),
                )
            record(
                "checkin_local_sem_hmac",
                assinatura_valida=validar_assinatura_licenca(obter_licenca_local()),
                cliente_valida=verificar_status_licenca()["valida"],
            )
            assert verificar_status_licenca()["valida"]
            # Remove o fingerprint do arquivo, simulando outra instalação com cache copiado.
            from getping.licensing import arquivo_fingerprint

            arquivo_fingerprint().write_text("DIFFERENT-INSTALLATION")
            record(
                "fingerprint_local_diferente", cliente_valida=verificar_status_licenca()["valida"]
            )
            assert verificar_status_licenca()["valida"]
            arquivo_fingerprint().write_text(fingerprint)
            # Resposta fabricada: o cliente não exige todos os campos autoritativos.
            fake = requests.Response()
            fake.status_code = 200
            fake.headers["content-type"] = "application/json"
            fake._content = b'{"valido":true}'
            with patch("getping.licensing._http_post", return_value=fake):
                ok, _, _ = sincronizar_licenca_com_servidor()
            record(
                "resposta_incompleta",
                aceita=ok,
                assinatura_valida=validar_assinatura_licenca(obter_licenca_local()),
            )
            assert ok
            # Endpoint e freshness podem ser trocados sem invalidar o selo.
            with conectar() as conn:
                conn.execute(
                    "UPDATE licenca_local SET servidor_admin_url='https://other-authority.invalid'"
                )
            record(
                "url_fora_do_hmac",
                assinatura_valida=validar_assinatura_licenca(obter_licenca_local()),
            )
            # A serialização HMAC com delimitador permite redistribuir campos textuais.
            base = {
                "valido": True,
                "cliente": "Fixture|Profissional",
                "tipo_plano": "Basico",
                "limite_hosts": 10,
                "limite_agentes": 0,
                "expira_em": expiry,
            }
            salvar_licenca_local(base, key, "https://fixture.invalid")
            with conectar() as conn:
                conn.execute(
                    "UPDATE licenca_local SET cliente_nome='Fixture',tipo_plano='Profissional|Basico'"
                )
            record(
                "hmac_delimitador_ambiguo",
                assinatura_valida=validar_assinatura_licenca(obter_licenca_local()),
            )
            # Quota não consulta validade; a API de agente é isenta do middleware de licença.
            with conectar() as conn:
                conn.execute(
                    "UPDATE licenca_local SET ultimo_checkin=?",
                    ((datetime.now() - timedelta(days=9)).strftime("%Y-%m-%d %H:%M:%S"),),
                )
            assert not verificar_status_licenca()["valida"]
            response = client_app.test_client().post(
                "/informacoes_agent",
                json={"hostname": "Fixture", "machine_uuid": "AUDIT-ZERO", "status_lan": True},
                headers={"Authorization": "Bearer " + token},
            )
            record("telemetria_com_offline_expirado", http=response.status_code)
            # Uma resposta antiga não é vinculada ao snapshot da chave local.
            base.update(cliente="Fixture", tipo_plano="Basico")
            salvar_licenca_local(base, key, "https://fixture.invalid")
            key_b = "FIXTURE-SECOND-KEY"
            with admin.app_context(), get_db() as conn:
                lid_b = conn.execute(
                    "INSERT INTO licencas(cliente_id,chave_licenca,data_emissao,data_expiracao) VALUES (?,?,'2026-01-01 00:00:00',?)",
                    (cid, key_b, expiry),
                ).lastrowid
                conn.execute(
                    "INSERT INTO license_bindings VALUES (?,?,NULL,datetime('now'))",
                    (lid_b, fingerprint),
                )
                conn.execute("UPDATE licencas SET status='cancelada' WHERE id=?", (lid,))

            def delayed_old_response(endpoint, payload):
                old = bridge(endpoint, payload)
                newer = bridge(endpoint, dict(payload, chave_licenca=key_b))
                salvar_licenca_local(newer.json(), key_b, "https://fixture.invalid")
                return old

            with patch("getping.licensing._http_post", side_effect=delayed_old_response):
                sincronizar_licenca_com_servidor()
            current = obter_licenca_local()
            record(
                "resposta_antiga_sobre_chave_nova",
                chave_nova_preservada=current["chave_licenca"] == key_b,
                status=current["status"],
            )
            assert current["chave_licenca"] == key_b and current["status"] == "cancelada"
            # Tentativas de fontes distintas consomem o bloqueio global da conta.
            from werkzeug.security import generate_password_hash

            with conectar() as conn:
                conn.execute(
                    "UPDATE usuarios SET senha_hash=?,troca_senha_obrigatoria=0 WHERE username='root'",
                    (generate_password_hash("Fixture-Root@123"),),
                )
            client_app.config["WTF_CSRF_ENABLED"] = True
            for source in range(3):
                c = client_app.test_client()
                c.get("/login")
                with c.session_transaction() as session:
                    csrf = session["_csrf_token"]
                for _ in range(5):
                    c.post(
                        "/login",
                        data={"username": "root", "senha": "wrong", "csrf_token": csrf},
                        environ_base={"REMOTE_ADDR": f"198.51.100.{source + 1}"},
                    )
            c = client_app.test_client()
            c.get("/login")
            with c.session_transaction() as session:
                csrf = session["_csrf_token"]
            response = c.post(
                "/login",
                data={"username": "root", "senha": "Fixture-Root@123", "csrf_token": csrf},
                environ_base={"REMOTE_ADDR": "198.51.100.99"},
            )
            record("login_bloqueio_global", login_correto_outro_ip_http=response.status_code)
            assert response.status_code == 429


if __name__ == "__main__":
    run()
