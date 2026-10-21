from datetime import datetime, timezone

from flask import Blueprint, abort, current_app, jsonify, request

from getping_admin.database.db import get_db
from getping_admin.licensing import valid_license_limits
from getping_admin.limits import enforce_limit
from getping_admin.validation import text

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


@api_bp.route("/licenca/validar", methods=["POST"])
def validar_licenca():
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        abort(400, description="Envie um objeto JSON válido.")
    chave = text(dados, "chave_licenca", maximum=128, required=True)
    fingerprint = text(dados, "fingerprint", maximum=256)
    versao = text(dados, "versao", maximum=64)
    enforce_limit("api-key", chave, current_app.config["API_RATE_LIMIT"] * 5)
    strict = current_app.config["REQUIRE_FINGERPRINT"]
    agora = datetime.now(timezone.utc).replace(microsecond=0)
    agora_str = agora.strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        # Serialize first activation so two different machines cannot both claim a key.
        conn.execute("BEGIN IMMEDIATE")
        licenca = conn.execute(
            """SELECT l.*, c.nome_empresa, c.ativo as cliente_ativo
            FROM licencas l JOIN clientes c ON l.cliente_id=c.id
            WHERE l.chave_licenca=?""",
            (chave,),
        ).fetchone()
        if not licenca:
            # Unknown keys do not produce unbounded event rows.
            return jsonify(
                valido=False, status="invalida", motivo="Licença inválida ou inexistente."
            ), 404

        def log(event, details):
            conn.execute(
                """INSERT INTO licenca_logs
                (licenca_id,chave_usada,evento,ip_origem,detalhes,criado_em)
                VALUES (?,?,?,?,?,?)""",
                (licenca["id"], "[redigida]", event, request.remote_addr, details, agora_str),
            )

        def denied(status, reason):
            return jsonify(valido=False, status=status, motivo=reason), 403

        if not licenca["cliente_ativo"]:
            return denied("suspensa", "A conta do cliente está suspensa/inativa.")
        if licenca["status"] != "ativa":
            return denied(licenca["status"], f"Licença {licenca['status']}.")
        try:
            data_exp = datetime.strptime(licenca["data_expiracao"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except (ValueError, TypeError):
            current_app.logger.error("Data inválida na licença id=%s", licenca["id"])
            abort(503, description="Licença com cadastro inconsistente. Contate o suporte.")
        if agora > data_exp:
            # Effective status is calculated everywhere, not mutated only by check-in.
            return denied("expirada", "Licença expirada.")
        if not valid_license_limits(licenca["limite_hosts"], licenca["limite_agentes"]):
            abort(503, description="Licença com cadastro inconsistente. Contate o suporte.")
        binding = conn.execute(
            "SELECT fingerprint FROM license_bindings WHERE licenca_id=?", (licenca["id"],)
        ).fetchone()
        if strict or binding is not None:
            if not fingerprint:
                abort(400, description="Fingerprint obrigatório para esta licença.")
            if binding is None or not binding["fingerprint"]:
                return denied(
                    "aguardando_vinculo", "A instalação precisa ser autorizada pelo administrador."
                )
            if binding["fingerprint"] != fingerprint:
                return denied("instancia_invalida", "Licença vinculada a outra instalação.")
        # Compatibility telemetry is not authorization. Never claim an installation here.
        if not strict and binding is None and fingerprint and not licenca["instancia_fingerprint"]:
            conn.execute(
                "UPDATE licencas SET instancia_fingerprint=? WHERE id=?",
                (fingerprint, licenca["id"]),
            )
        conn.execute(
            "UPDATE licencas SET ultimo_checkin_em=? WHERE id=?", (agora_str, licenca["id"])
        )
        # Aggregate success events. Blocked/invalid requests cannot flood the log table.
        interval = current_app.config["CHECKIN_LOG_INTERVAL_SECONDS"]
        recent = conn.execute(
            """SELECT 1 FROM licenca_logs
            WHERE licenca_id=? AND evento='checkin_sucesso'
            AND criado_em >= datetime(?, ?) LIMIT 1""",
            (licenca["id"], agora_str, f"-{interval} seconds"),
        ).fetchone()
        if not recent:
            log("checkin_sucesso", f"Check-in autorizado | versão {versao}")
        return jsonify(
            valido=True,
            chave_licenca=chave,
            cliente=licenca["nome_empresa"],
            tipo_plano=licenca["tipo_plano"],
            limite_hosts=licenca["limite_hosts"],
            limite_agentes=licenca["limite_agentes"],
            expira_em=licenca["data_expiracao"],
            expira_em_iso=data_exp.isoformat(),
            dias_restantes=max(0, (data_exp - agora).days),
            mensagem="Licença ativa e autorizada.",
        ), 200
