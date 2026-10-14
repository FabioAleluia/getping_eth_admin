from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from database.db import get_db

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


@api_bp.route("/licenca/validar", methods=["POST"])
def validar_licenca():
    """Endpoint REST para validação de licença pelo GetPing."""
    dados = request.get_json(silent=True) or {}
    chave = dados.get("chave_licenca", "").strip()
    fingerprint = dados.get("fingerprint", "").strip()
    versao_getping = dados.get("versao", "").strip()
    ip_origem = request.headers.get("X-Forwarded-For", request.remote_addr)

    if not chave:
        return jsonify({
            "valido": False,
            "motivo": "Chave de licença não fornecida."
        }), 400

    agora = datetime.now(timezone.utc)
    agora_str = agora.strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as conn:
        licenca = conn.execute(
            """
            SELECT l.*, c.nome_empresa, c.ativo as cliente_ativo
            FROM licencas l
            JOIN clientes c ON l.cliente_id = c.id
            WHERE l.chave_licenca = ?
            """,
            (chave,)
        ).fetchone()

        if not licenca:
            conn.execute(
                """
                INSERT INTO licenca_logs (chave_usada, evento, ip_origem, detalhes, criado_em)
                VALUES (?, 'chave_invalida', ?, ?, ?)
                """,
                (chave, ip_origem, f"Versão: {versao_getping} | FP: {fingerprint}", agora_str)
            )
            return jsonify({
                "valido": False,
                "status": "invalida",
                "motivo": "Licença inválida ou inexistente."
            }), 404

        if not licenca["cliente_ativo"]:
            conn.execute(
                """
                INSERT INTO licenca_logs (licenca_id, chave_usada, evento, ip_origem, detalhes, criado_em)
                VALUES (?, ?, 'cliente_inativo', ?, ?, ?)
                """,
                (licenca["id"], chave, ip_origem, f"Cliente inativado | FP: {fingerprint}", agora_str)
            )
            return jsonify({
                "valido": False,
                "status": "suspensa",
                "motivo": "A conta do cliente está suspensa/inativa."
            }), 403

        if licenca["status"] != "ativa":
            conn.execute(
                """
                INSERT INTO licenca_logs (licenca_id, chave_usada, evento, ip_origem, detalhes, criado_em)
                VALUES (?, ?, 'licenca_bloqueada', ?, ?, ?)
                """,
                (licenca["id"], chave, ip_origem, f"Status atual: {licenca['status']} | FP: {fingerprint}", agora_str)
            )
            return jsonify({
                "valido": False,
                "status": licenca["status"],
                "motivo": f"Licença {licenca['status']}."
            }), 403

        # Verifica data de expiração
        data_exp = datetime.strptime(licenca["data_expiracao"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if agora > data_exp:
            conn.execute(
                "UPDATE licencas SET status = 'expirada' WHERE id = ?",
                (licenca["id"],)
            )
            conn.execute(
                """
                INSERT INTO licenca_logs (licenca_id, chave_usada, evento, ip_origem, detalhes, criado_em)
                VALUES (?, ?, 'licenca_expirada', ?, ?, ?)
                """,
                (licenca["id"], chave, ip_origem, f"Expirada em {licenca['data_expiracao']} | FP: {fingerprint}", agora_str)
            )
            return jsonify({
                "valido": False,
                "status": "expirada",
                "motivo": "Licença expirada."
            }), 403

        # Atualiza check-in e fingerprint se não houver ou associar
        instancia_fp = licenca["instancia_fingerprint"]
        if not instancia_fp and fingerprint:
            conn.execute(
                "UPDATE licencas SET instancia_fingerprint = ?, ultimo_checkin_em = ? WHERE id = ?",
                (fingerprint, agora_str, licenca["id"])
            )
        else:
            conn.execute(
                "UPDATE licencas SET ultimo_checkin_em = ? WHERE id = ?",
                (agora_str, licenca["id"])
            )

        conn.execute(
            """
            INSERT INTO licenca_logs (licenca_id, chave_usada, evento, ip_origem, detalhes, criado_em)
            VALUES (?, ?, 'checkin_sucesso', ?, ?, ?)
            """,
            (licenca["id"], chave, ip_origem, f"Check-in OK | v{versao_getping} | FP: {fingerprint}", agora_str)
        )

        dias_restantes = (data_exp - agora).days

        return jsonify({
            "valido": True,
            "chave_licenca": licenca["chave_licenca"],
            "cliente": licenca["nome_empresa"],
            "tipo_plano": licenca["tipo_plano"],
            "limite_hosts": licenca["limite_hosts"],
            "limite_agentes": licenca["limite_agentes"],
            "expira_em": licenca["data_expiracao"],
            "dias_restantes": max(0, dias_restantes),
            "mensagem": "Licença ativa e autorizada."
        }), 200
