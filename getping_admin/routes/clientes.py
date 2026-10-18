from datetime import datetime, timezone

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from getping_admin.audit import audit
from getping_admin.auth import login_required
from getping_admin.database.db import get_db
from getping_admin.pagination import page_parameters, page_rows
from getping_admin.validation import text, validate_form

clientes_bp = Blueprint("clientes", __name__, url_prefix="/clientes")


@clientes_bp.route("/")
@login_required
def listar():
    limit, offset = page_parameters()
    busca = text(request.args, "busca", maximum=200)
    with get_db() as conn:
        if busca:
            clientes = conn.execute(
                """
                SELECT c.*, 
                       (SELECT COUNT(*) FROM licencas l WHERE l.cliente_id = c.id) as total_licencas,
                       (SELECT COUNT(*) FROM licencas l WHERE l.cliente_id = c.id AND l.status = 'ativa' AND l.data_expiracao >= datetime('now') AND c.ativo=1) as licencas_ativas
                FROM clientes c
                WHERE c.nome_empresa LIKE ? OR c.responsavel_nome LIKE ? OR c.responsavel_email LIKE ?
                ORDER BY c.nome_empresa ASC, c.id ASC LIMIT ? OFFSET ?
                """,
                (f"%{busca}%", f"%{busca}%", f"%{busca}%", limit, offset),
            ).fetchall()
        else:
            clientes = conn.execute(
                """
                SELECT c.*, 
                       (SELECT COUNT(*) FROM licencas l WHERE l.cliente_id = c.id) as total_licencas,
                       (SELECT COUNT(*) FROM licencas l WHERE l.cliente_id = c.id AND l.status = 'ativa' AND l.data_expiracao >= datetime('now') AND c.ativo=1) as licencas_ativas
                FROM clientes c
                ORDER BY c.nome_empresa ASC, c.id ASC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

    return render_template("clientes/listar.html", clientes=page_rows(clientes), busca=busca)


@clientes_bp.route("/novo", methods=["GET", "POST"])
@login_required
@validate_form
def novo():
    if g.user and g.user["papel"] == "assistente":
        flash("Usuários com perfil Assistente não têm permissão para cadastrar clientes.", "danger")
        return redirect(url_for("clientes.listar"))

    if request.method == "POST":
        nome_empresa = request.form.get("nome_empresa", "").strip()
        responsavel_nome = request.form.get("responsavel_nome", "").strip()
        responsavel_email = request.form.get("responsavel_email", "").strip()
        telefone = request.form.get("telefone", "").strip()
        cnpj_cpf = request.form.get("cnpj_cpf", "").strip()
        observacoes = request.form.get("observacoes", "").strip()

        if not nome_empresa or not responsavel_nome:
            flash("Nome da empresa e nome do responsável são obrigatórios.", "danger")
            return render_template("clientes/form.html", acao="novo", cliente={})

        agora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO clientes (nome_empresa, responsavel_nome, responsavel_email, telefone, cnpj_cpf, observacoes, ativo, criado_em)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    nome_empresa,
                    responsavel_nome,
                    responsavel_email,
                    telefone,
                    cnpj_cpf,
                    observacoes,
                    agora,
                ),
            )
            audit(
                conn,
                "create",
                "cliente",
                conn.execute("SELECT last_insert_rowid()").fetchone()[0],
                after={"nome_empresa": nome_empresa},
            )
        flash("Cliente cadastrado com sucesso!", "success")
        return redirect(url_for("clientes.listar"))

    return render_template("clientes/form.html", acao="novo", cliente={})


@clientes_bp.route("/<int:id>/editar", methods=["GET", "POST"])
@login_required
@validate_form
def editar(id):
    with get_db() as conn:
        cliente = conn.execute("SELECT * FROM clientes WHERE id = ?", (id,)).fetchone()
        if not cliente:
            flash("Cliente não encontrado.", "danger")
            return redirect(url_for("clientes.listar"))

        if request.method == "POST":
            # Perfil assistente só pode alterar E-mail de Contato e Telefone
            if g.user and g.user["papel"] == "assistente":
                responsavel_email = request.form.get("responsavel_email", "").strip()
                telefone = request.form.get("telefone", "").strip()

                conn.execute(
                    """
                    UPDATE clientes
                    SET responsavel_email = ?, telefone = ?
                    WHERE id = ?
                    """,
                    (responsavel_email, telefone, id),
                )
                audit(
                    conn,
                    "update_contact",
                    "cliente",
                    id,
                    before={
                        "responsavel_email": cliente["responsavel_email"],
                        "telefone": cliente["telefone"],
                    },
                    after={"responsavel_email": responsavel_email, "telefone": telefone},
                )
                flash("Informações de contato do cliente atualizadas com sucesso!", "success")
                return redirect(url_for("clientes.listar"))

            nome_empresa = request.form.get("nome_empresa", "").strip()
            responsavel_nome = request.form.get("responsavel_nome", "").strip()
            responsavel_email = request.form.get("responsavel_email", "").strip()
            telefone = request.form.get("telefone", "").strip()
            cnpj_cpf = request.form.get("cnpj_cpf", "").strip()
            observacoes = request.form.get("observacoes", "").strip()
            ativo = 1 if request.form.get("ativo") == "1" else 0

            if not nome_empresa or not responsavel_nome:
                flash("Nome da empresa e responsável são obrigatórios.", "danger")
                return render_template("clientes/form.html", acao="editar", cliente=cliente)

            conn.execute(
                """
                UPDATE clientes
                SET nome_empresa = ?, responsavel_nome = ?, responsavel_email = ?, telefone = ?, cnpj_cpf = ?, observacoes = ?, ativo = ?
                WHERE id = ?
                """,
                (
                    nome_empresa,
                    responsavel_nome,
                    responsavel_email,
                    telefone,
                    cnpj_cpf,
                    observacoes,
                    ativo,
                    id,
                ),
            )
            fields = (
                "nome_empresa",
                "responsavel_nome",
                "responsavel_email",
                "telefone",
                "cnpj_cpf",
                "observacoes",
                "ativo",
            )
            updated = conn.execute("SELECT * FROM clientes WHERE id=?", (id,)).fetchone()
            audit(
                conn,
                "update",
                "cliente",
                id,
                before={k: cliente[k] for k in fields},
                after={k: updated[k] for k in fields},
            )
            flash("Cliente atualizado com sucesso!", "success")
            return redirect(url_for("clientes.listar"))

    return render_template("clientes/form.html", acao="editar", cliente=cliente)


@clientes_bp.route("/<int:id>/excluir", methods=["POST"])
@login_required
@validate_form
def excluir(id):
    if g.user and g.user["papel"] == "assistente":
        flash("Usuários com perfil Assistente não têm permissão para excluir clientes.", "danger")
        return redirect(url_for("clientes.listar"))

    with get_db() as conn:
        # Verifica se possui licenças vinculadas
        licencas_count = conn.execute(
            "SELECT COUNT(*) as total FROM licencas WHERE cliente_id = ?", (id,)
        ).fetchone()["total"]

        if licencas_count > 0:
            flash(
                f"Não é possível excluir o cliente pois ele possui {licencas_count} licença(s) vinculada(s). Desative-o ou remova as licenças primeiro.",
                "warning",
            )
            return redirect(url_for("clientes.listar"))

        audit(conn, "delete", "cliente", id)
        conn.execute("DELETE FROM clientes WHERE id = ?", (id,))
        flash("Cliente excluído com sucesso!", "success")
    return redirect(url_for("clientes.listar"))
