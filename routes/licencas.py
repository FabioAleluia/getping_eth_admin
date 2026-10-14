from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from database.db import get_db, gerar_chave_licenca
from routes.auth import login_required

licencas_bp = Blueprint("licencas", __name__, url_prefix="/licencas")


@licencas_bp.route("/")
@login_required
def listar():
    status_filtro = request.args.get("status", "").strip()
    busca = request.args.get("busca", "").strip()

    sql = """
        SELECT l.*, c.nome_empresa, c.responsavel_nome
        FROM licencas l
        JOIN clientes c ON l.cliente_id = c.id
        WHERE 1=1
    """
    params = []

    if status_filtro:
        sql += " AND l.status = ?"
        params.append(status_filtro)

    if busca:
        sql += " AND (l.chave_licenca LIKE ? OR c.nome_empresa LIKE ?)"
        params.extend([f"%{busca}%", f"%{busca}%"])

    sql += " ORDER BY l.id DESC"

    with get_db() as conn:
        licencas = conn.execute(sql, params).fetchall()

    return render_template(
        "licencas/listar.html",
        licencas=licencas,
        status_filtro=status_filtro,
        busca=busca,
    )


@licencas_bp.route("/nova", methods=["GET", "POST"])
@login_required
def nova():
    if g.user and g.user["papel"] == "assistente":
        flash("Usuários com perfil Assistente não têm permissão para emitir licenças.", "danger")
        return redirect(url_for("licencas.listar"))

    with get_db() as conn:
        clientes = conn.execute("SELECT id, nome_empresa FROM clientes WHERE ativo = 1 ORDER BY nome_empresa").fetchall()

        if request.method == "POST":
            cliente_id = request.form.get("cliente_id")
            tipo_plano = request.form.get("tipo_plano", "Basico")
            limite_hosts = int(request.form.get("limite_hosts", 10))
            limite_agentes = int(request.form.get("limite_agentes", 5))
            dias_validade = int(request.form.get("dias_validade", 30))
            observacoes = request.form.get("observacoes", "").strip()

            if not cliente_id:
                flash("Selecione um cliente.", "danger")
                return render_template("licencas/form.html", acao="nova", clientes=clientes, licenca={})

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
                (cliente_id, chave, tipo_plano, limite_hosts, limite_agentes, data_emissao, data_expiracao, observacoes)
            )
            flash(f"Licença {chave} gerada com sucesso!", "success")
            return redirect(url_for("licencas.listar"))

    hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return render_template("licencas/form.html", acao="nova", clientes=clientes, licenca={}, hoje=hoje)


@licencas_bp.route("/<int:id>/editar", methods=["GET", "POST"])
@login_required
def editar(id):
    with get_db() as conn:
        licenca = conn.execute(
            """
            SELECT l.*, c.nome_empresa 
            FROM licencas l 
            JOIN clientes c ON l.cliente_id = c.id 
            WHERE l.id = ?
            """,
            (id,)
        ).fetchone()

        if not licenca:
            flash("Licença não encontrada.", "danger")
            return redirect(url_for("licencas.listar"))

        clientes = conn.execute("SELECT id, nome_empresa FROM clientes WHERE ativo = 1 ORDER BY nome_empresa").fetchall()

        if request.method == "POST":
            tipo_plano = request.form.get("tipo_plano", licenca["tipo_plano"])
            limite_hosts = int(request.form.get("limite_hosts", licenca["limite_hosts"]))
            limite_agentes = int(request.form.get("limite_agentes", licenca["limite_agentes"]))
            status = request.form.get("status", licenca["status"])
            data_expiracao = request.form.get("data_expiracao", licenca["data_expiracao"][:10]) + " 23:59:59"
            observacoes = request.form.get("observacoes", "").strip()

            conn.execute(
                """
                UPDATE licencas
                SET tipo_plano = ?, limite_hosts = ?, limite_agentes = ?, status = ?, data_expiracao = ?, observacoes = ?
                WHERE id = ?
                """,
                (tipo_plano, limite_hosts, limite_agentes, status, data_expiracao, observacoes, id)
            )
            flash("Licença atualizada com sucesso!", "success")
            return redirect(url_for("licencas.listar"))

    return render_template("licencas/form.html", acao="editar", clientes=clientes, licenca=licenca)


@licencas_bp.route("/<int:id>/status", methods=["POST"])
@login_required
def alterar_status(id):
    novo_status = request.form.get("novo_status")
    if novo_status not in ("ativa", "suspensa", "cancelada"):
        flash("Status inválido.", "danger")
        return redirect(url_for("licencas.listar"))

    with get_db() as conn:
        conn.execute("UPDATE licencas SET status = ? WHERE id = ?", (novo_status, id))
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
            (id,)
        ).fetchone()

        if not licenca:
            flash("Licença não encontrada.", "danger")
            return redirect(url_for("licencas.listar"))

        logs = conn.execute(
            "SELECT * FROM licenca_logs WHERE licenca_id = ? ORDER BY id DESC LIMIT 50",
            (id,)
        ).fetchall()

    return render_template("licencas/detalhes.html", licenca=licenca, logs=logs)


@licencas_bp.route("/<int:id>/excluir", methods=["POST"])
@login_required
def excluir(id):
    # Proteção de permissão: somente superadmin pode excluir fisicamente
    if not g.user or g.user["papel"] != "superadmin":
        flash("Apenas usuários com perfil Superadmin podem excluir licenças permanentemente. Considere suspender ou cancelar a licença.", "danger")
        return redirect(url_for("licencas.listar"))

    with get_db() as conn:
        licenca = conn.execute("SELECT id, chave_licenca, status FROM licencas WHERE id = ?", (id,)).fetchone()
        if not licenca:
            flash("Licença não encontrada.", "danger")
            return redirect(url_for("licencas.listar"))

        # Executa a exclusão física
        conn.execute("DELETE FROM licencas WHERE id = ?", (id,))
        flash(f"Licença {licenca['chave_licenca']} foi excluída com sucesso!", "success")

    return redirect(url_for("licencas.listar"))
