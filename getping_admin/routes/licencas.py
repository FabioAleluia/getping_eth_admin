from datetime import datetime, timedelta, timezone

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.security import check_password_hash

from getping_admin.audit import audit
from getping_admin.auth import login_required
from getping_admin.database.db import get_db
from getping_admin.licensing import effective_status, gerar_chave_licenca
from getping_admin.pagination import page_parameters, page_rows
from getping_admin.validation import (
    PLANS,
    STATUSES,
    choice,
    expiration,
    integer,
    text,
    validate_form,
)

licencas_bp = Blueprint("licencas", __name__, url_prefix="/licencas")


@licencas_bp.route("/")
@login_required
def listar():
    status_filtro = request.args.get("status", "").strip()
    busca = text(request.args, "busca", maximum=200)

    limit, offset = page_parameters()
    state = effective_status()
    sql = f"""
        SELECT l.*, {state} AS status_efetivo, c.nome_empresa, c.responsavel_nome
        FROM licencas l
        JOIN clientes c ON l.cliente_id = c.id
        WHERE 1=1
    """
    params = []

    if status_filtro:
        sql += f" AND ({state}) = ?"
        params.append(status_filtro)

    if busca:
        sql += " AND (l.chave_licenca LIKE ? OR c.nome_empresa LIKE ?)"
        params.extend([f"%{busca}%", f"%{busca}%"])

    sql += " ORDER BY l.id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db() as conn:
        licencas = page_rows(
            [dict(r, status=r["status_efetivo"]) for r in conn.execute(sql, params).fetchall()]
        )

    return render_template(
        "licencas/listar.html",
        licencas=licencas,
        status_filtro=status_filtro,
        busca=busca,
    )


@licencas_bp.route("/nova", methods=["GET", "POST"])
@login_required
@validate_form
def nova():
    if g.user and g.user["papel"] == "assistente":
        flash("Usuários com perfil Assistente não têm permissão para emitir licenças.", "danger")
        return redirect(url_for("licencas.listar"))

    with get_db() as conn:
        clientes = conn.execute(
            "SELECT id, nome_empresa FROM clientes WHERE ativo = 1 ORDER BY nome_empresa"
        ).fetchall()

        if request.method == "POST":
            cliente_id = integer(request.form, "cliente_id", 0, 1, 2147483647)
            tipo_plano = choice(request.form, "tipo_plano", "Basico", PLANS)
            limite_hosts = integer(request.form, "limite_hosts", 10, 1, 10000)
            limite_agentes = integer(request.form, "limite_agentes", 5, 0, 10000)
            dias_validade = integer(request.form, "dias_validade", 30, 1, 3650)
            observacoes = request.form.get("observacoes", "").strip()

            if not conn.execute(
                "SELECT 1 FROM clientes WHERE id=? AND ativo=1", (cliente_id,)
            ).fetchone():
                flash("Selecione um cliente.", "danger")
                return render_template(
                    "licencas/form.html", acao="nova", clientes=clientes, licenca={}
                )

            agora = datetime.now(timezone.utc)
            data_emissao = agora.strftime("%Y-%m-%d %H:%M:%S")
            data_expiracao = (agora + timedelta(days=dias_validade)).strftime("%Y-%m-%d 23:59:59")
            chave = gerar_chave_licenca()

            conn.execute(
                """
                INSERT INTO licencas (
                    cliente_id, chave_licenca, tipo_plano, limite_hosts, limite_agentes,
                    status, data_emissao, data_expiracao, observacoes
                ) VALUES (?, ?, ?, ?, ?, 'ativa', ?, ?, ?)
                """,
                (
                    cliente_id,
                    chave,
                    tipo_plano,
                    limite_hosts,
                    limite_agentes,
                    data_emissao,
                    data_expiracao,
                    observacoes,
                ),
            )
            # New licenses are secure by default; existing licenses are migrated gradually.
            new_id = conn.execute(
                "SELECT id FROM licencas WHERE chave_licenca=?", (chave,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO license_bindings VALUES (?,NULL,?,datetime('now'))",
                (new_id, g.user["id"]),
            )
            audit(
                conn,
                "create",
                "licenca",
                conn.execute("SELECT id FROM licencas WHERE chave_licenca=?", (chave,)).fetchone()[
                    0
                ],
                after={
                    "cliente_id": cliente_id,
                    "tipo_plano": tipo_plano,
                    "limite_hosts": limite_hosts,
                    "limite_agentes": limite_agentes,
                    "data_expiracao": data_expiracao,
                },
            )
            flash(
                f"Licença {chave} gerada com sucesso! Solicite ao superadmin a autorização da instalação nos detalhes antes de usar.",
                "success",
            )
            return redirect(url_for("licencas.listar"))

    hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return render_template(
        "licencas/form.html", acao="nova", clientes=clientes, licenca={}, hoje=hoje
    )


@licencas_bp.route("/<int:id>/editar", methods=["GET", "POST"])
@login_required
@validate_form
def editar(id):
    if g.user["papel"] == "assistente" and not current_app.config["ALLOW_ASSISTANT_LICENSE_EDITS"]:
        abort(403, description="Assistentes não podem alterar condições comerciais da licença.")
    with get_db() as conn:
        licenca = conn.execute(
            """
            SELECT l.*, c.nome_empresa 
            FROM licencas l 
            JOIN clientes c ON l.cliente_id = c.id 
            WHERE l.id = ?
            """,
            (id,),
        ).fetchone()

        if not licenca:
            flash("Licença não encontrada.", "danger")
            return redirect(url_for("licencas.listar"))

        clientes = conn.execute(
            "SELECT id, nome_empresa FROM clientes WHERE ativo = 1 ORDER BY nome_empresa"
        ).fetchall()

        if request.method == "POST":
            tipo_plano = choice(request.form, "tipo_plano", licenca["tipo_plano"], PLANS)
            limite_hosts = integer(request.form, "limite_hosts", licenca["limite_hosts"], 1, 10000)
            limite_agentes = integer(
                request.form, "limite_agentes", licenca["limite_agentes"], 0, 10000
            )
            status = choice(request.form, "status", licenca["status"], STATUSES)
            data_expiracao = expiration(
                request.form.get("data_expiracao", licenca["data_expiracao"][:10])
            )
            observacoes = request.form.get("observacoes", "").strip()

            conn.execute(
                """
                UPDATE licencas
                SET tipo_plano = ?, limite_hosts = ?, limite_agentes = ?, status = ?, data_expiracao = ?, observacoes = ?
                WHERE id = ?
                """,
                (tipo_plano, limite_hosts, limite_agentes, status, data_expiracao, observacoes, id),
            )
            fields = (
                "tipo_plano",
                "limite_hosts",
                "limite_agentes",
                "status",
                "data_expiracao",
                "observacoes",
            )
            audit(
                conn,
                "update",
                "licenca",
                id,
                before={k: licenca[k] for k in fields},
                after={
                    "tipo_plano": tipo_plano,
                    "limite_hosts": limite_hosts,
                    "limite_agentes": limite_agentes,
                    "status": status,
                    "data_expiracao": data_expiracao,
                    "observacoes": observacoes,
                },
            )
            flash("Licença atualizada com sucesso!", "success")
            return redirect(url_for("licencas.listar"))

    return render_template("licencas/form.html", acao="editar", clientes=clientes, licenca=licenca)


@licencas_bp.route("/<int:id>/status", methods=["POST"])
@login_required
@validate_form
def alterar_status(id):
    if g.user["papel"] == "assistente" and not current_app.config["ALLOW_ASSISTANT_LICENSE_EDITS"]:
        abort(403, description="Assistentes não podem alterar status da licença.")
    novo_status = request.form.get("novo_status")
    if novo_status not in ("ativa", "suspensa", "cancelada"):
        flash("Status inválido.", "danger")
        return redirect(url_for("licencas.listar"))

    with get_db() as conn:
        old = conn.execute("SELECT status FROM licencas WHERE id=?", (id,)).fetchone()
        if not old:
            abort(404)
        conn.execute("UPDATE licencas SET status = ? WHERE id = ?", (novo_status, id))
        audit(
            conn, "status", "licenca", id, before={"status": old[0]}, after={"status": novo_status}
        )
        flash(f"Status da licença alterado para '{novo_status}'.", "info")
    return redirect(url_for("licencas.listar"))


@licencas_bp.route("/<int:id>/detalhes")
@login_required
def detalhes(id):
    with get_db() as conn:
        licenca = conn.execute(
            """
            SELECT l.*, c.nome_empresa, c.responsavel_nome, c.responsavel_email
            FROM licencas l
            JOIN clientes c ON l.cliente_id = c.id
            WHERE l.id = ?
            """,
            (id,),
        ).fetchone()

        if not licenca:
            flash("Licença não encontrada.", "danger")
            return redirect(url_for("licencas.listar"))

        logs = conn.execute(
            "SELECT * FROM licenca_logs WHERE licenca_id = ? ORDER BY id DESC LIMIT 50", (id,)
        ).fetchall()

        state = conn.execute(
            f"SELECT {effective_status()} FROM licencas l JOIN clientes c ON c.id=l.cliente_id WHERE l.id=?",
            (id,),
        ).fetchone()[0]
        binding = conn.execute(
            "SELECT fingerprint FROM license_bindings WHERE licenca_id=?", (id,)
        ).fetchone()
        licenca = dict(
            licenca,
            status=state,
            binding_required=binding is not None or current_app.config["REQUIRE_FINGERPRINT"],
            authorized_fingerprint=binding["fingerprint"] if binding else None,
        )
    return render_template("licencas/detalhes.html", licenca=licenca, logs=logs)


@licencas_bp.route("/<int:id>/excluir", methods=["POST"])
@login_required
@validate_form
def excluir(id):
    # Proteção de permissão: somente superadmin pode excluir fisicamente
    if not g.user or g.user["papel"] != "superadmin":
        flash(
            "Apenas usuários com perfil Superadmin podem excluir licenças permanentemente. Considere suspender ou cancelar a licença.",
            "danger",
        )
        return redirect(url_for("licencas.listar"))

    with get_db() as conn:
        licenca = conn.execute(
            "SELECT id, chave_licenca, status FROM licencas WHERE id = ?", (id,)
        ).fetchone()
        if not licenca:
            flash("Licença não encontrada.", "danger")
            return redirect(url_for("licencas.listar"))

        # Executa a exclusão física
        audit(conn, "delete", "licenca", id, before={"status": licenca["status"]})
        conn.execute("DELETE FROM licencas WHERE id = ?", (id,))
        flash(f"Licença {licenca['chave_licenca']} foi excluída com sucesso!", "success")

    return redirect(url_for("licencas.listar"))


@licencas_bp.route("/<int:id>/liberar-instancia", methods=["POST"])
@login_required
@validate_form
def liberar_instancia(id):
    if g.user["papel"] != "superadmin":
        abort(403)
    with get_db() as conn:
        row = conn.execute(
            "SELECT instancia_fingerprint FROM licencas WHERE id=?", (id,)
        ).fetchone()
        if not row:
            abort(404)
        conn.execute(
            """INSERT INTO license_bindings VALUES (?,NULL,?,datetime('now'))
            ON CONFLICT(licenca_id) DO UPDATE SET fingerprint=NULL,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
            (id, g.user["id"]),
        )
        conn.execute("UPDATE licencas SET instancia_fingerprint=NULL WHERE id=?", (id,))
        audit(conn, "release_instance", "licenca", id, before={"vinculada": bool(row[0])})
    flash(
        "Vínculo removido. Autorize explicitamente a nova instalação antes de validar.", "success"
    )
    return redirect(url_for("licencas.detalhes", id=id))


@licencas_bp.post("/<int:id>/vincular-instancia")
@login_required
@validate_form
def vincular_instancia(id):
    if g.user["papel"] != "superadmin":
        abort(403)
    fingerprint = text(request.form, "fingerprint", maximum=256, required=True)
    password = request.form.get("senha_atual", "")
    from getping_admin.limits import enforce_limit

    enforce_limit("bind-admin", str(g.user["id"]), 5)
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        user = conn.execute(
            "SELECT senha_hash FROM admin_usuarios WHERE id=?", (g.user["id"],)
        ).fetchone()
        if not check_password_hash(user["senha_hash"], password):
            abort(403, description="Senha atual incorreta.")
        if not conn.execute("SELECT 1 FROM licencas WHERE id=?", (id,)).fetchone():
            abort(404)
        before = conn.execute(
            "SELECT fingerprint FROM license_bindings WHERE licenca_id=?", (id,)
        ).fetchone()
        conn.execute(
            """INSERT INTO license_bindings VALUES (?,?,?,datetime('now'))
            ON CONFLICT(licenca_id) DO UPDATE SET fingerprint=excluded.fingerprint,
            updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
            (id, fingerprint, g.user["id"]),
        )
        audit(
            conn,
            "authorize_instance",
            "licenca",
            id,
            before={"authorized": bool(before and before[0])},
            after={"authorized": True},
        )
    flash("Instalação autorizada. Esta licença agora exige o fingerprint aprovado.", "success")
    return redirect(url_for("licencas.detalhes", id=id))
