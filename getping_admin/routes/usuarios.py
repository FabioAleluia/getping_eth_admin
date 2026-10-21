from datetime import datetime, timezone

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from getping_admin.audit import audit
from getping_admin.auth import login_required
from getping_admin.database.db import get_db
from getping_admin.identity import identity_conflict, normalize_identifier
from getping_admin.pagination import page_parameters, page_rows
from getping_admin.security import validar_complexidade_senha
from getping_admin.validation import text, validate_form

usuarios_bp = Blueprint("usuarios", __name__, url_prefix="/usuarios")


@usuarios_bp.route("/")
@login_required
def listar():
    # Apenas superadmin e gestor podem acessar a lista de usuários
    if g.user["papel"] not in ("superadmin", "gestor"):
        flash("Acesso não autorizado para o seu perfil.", "danger")
        return redirect(url_for("dashboard.index"))

    limit, offset = page_parameters()
    busca = text(request.args, "busca", maximum=200)
    with get_db() as conn:
        if busca:
            usuarios = conn.execute(
                """
                SELECT id, nome, username, email, papel, ativo, trocar_senha, criado_em, ultimo_login
                FROM admin_usuarios
                WHERE nome LIKE ? OR username LIKE ? OR email LIKE ?
                ORDER BY id ASC LIMIT ? OFFSET ?
                """,
                (f"%{busca}%", f"%{busca}%", f"%{busca}%", limit, offset),
            ).fetchall()
        else:
            usuarios = conn.execute(
                """
                SELECT id, nome, username, email, papel, ativo, trocar_senha, criado_em, ultimo_login
                FROM admin_usuarios
                ORDER BY id ASC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

    return render_template("usuarios/listar.html", usuarios=page_rows(usuarios), busca=busca)


@usuarios_bp.route("/novo", methods=["GET", "POST"])
@login_required
@validate_form
def novo():
    if g.user["papel"] not in ("superadmin", "gestor"):
        flash("Acesso não autorizado.", "danger")
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        username = normalize_identifier(request.form.get("username", ""))
        email = normalize_identifier(request.form.get("email", ""))
        papel = request.form.get("papel", "assistente")
        senha_inicial = request.form.get("senha_inicial", "")
        exigir_troca = 1 if request.form.get("exigir_troca") == "1" else 0

        # Gestores só podem criar Assistentes
        if g.user["papel"] == "gestor" and papel != "assistente":
            flash("Gestores só têm permissão para criar usuários com perfil Assistente.", "danger")
            return render_template("usuarios/form.html", acao="novo", usuario={})

        if papel not in ("gestor", "assistente"):
            flash("Perfil inválido.", "danger")
            return render_template("usuarios/form.html", acao="novo", usuario={})

        if not nome or not username or not email or not senha_inicial:
            flash("Todos os campos são obrigatórios.", "danger")
            return render_template("usuarios/form.html", acao="novo", usuario={})

        valido, msg_erro = validar_complexidade_senha(senha_inicial)
        if not valido:
            flash(msg_erro, "danger")
            return render_template(
                "usuarios/form.html",
                acao="novo",
                usuario={"nome": nome, "username": username, "email": email, "papel": papel},
            )

        agora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        senha_hash = generate_password_hash(senha_inicial)

        with get_db() as conn:
            # Checa duplicidade de username ou email
            existente = identity_conflict(conn, username, email)
            if existente:
                flash("Nome de usuário ou e-mail já cadastrado.", "danger")
                return render_template(
                    "usuarios/form.html",
                    acao="novo",
                    usuario={"nome": nome, "username": username, "email": email, "papel": papel},
                )

            conn.execute(
                """
                INSERT INTO admin_usuarios (nome, username, email, senha_hash, papel, ativo, trocar_senha, criado_em)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (nome, username, email, senha_hash, papel, exigir_troca, agora),
            )

            audit(
                conn,
                "create",
                "usuario",
                conn.execute(
                    "SELECT id FROM admin_usuarios WHERE username=?", (username,)
                ).fetchone()[0],
                after={"nome": nome, "email": email, "papel": papel},
            )
        flash(f"Usuário '{username}' cadastrado com sucesso!", "success")
        return redirect(url_for("usuarios.listar"))

    return render_template("usuarios/form.html", acao="novo", usuario={})


@usuarios_bp.route("/<int:id>/editar", methods=["GET", "POST"])
@login_required
@validate_form
def editar(id):
    if g.user["papel"] not in ("superadmin", "gestor"):
        flash("Acesso não autorizado.", "danger")
        return redirect(url_for("dashboard.index"))

    with get_db() as conn:
        usuario = conn.execute("SELECT * FROM admin_usuarios WHERE id = ?", (id,)).fetchone()
        if not usuario:
            flash("Usuário não encontrado.", "danger")
            return redirect(url_for("usuarios.listar"))

        # A própria conta só pode ser alterada pelo perfil, que exige a senha atual.
        if usuario["id"] == g.user["id"]:
            if request.method == "POST":
                from flask import abort

                abort(403, description="Use Meu Perfil para alterar sua própria conta.")
            return redirect(url_for("auth.perfil"))

        # Gestores não podem editar o superadmin nem outros gestores
        if (
            g.user["papel"] == "gestor"
            and usuario["papel"] in ("superadmin", "gestor")
            and usuario["id"] != g.user["id"]
        ):
            flash("Gestores não podem editar outros gestores ou administradores.", "danger")
            return redirect(url_for("usuarios.listar"))

        if request.method == "POST":
            nome = request.form.get("nome", "").strip()
            email = normalize_identifier(request.form.get("email", ""))
            papel = request.form.get("papel", usuario["papel"])
            ativo = 1 if request.form.get("ativo") == "1" else 0
            trocar_senha = 1 if request.form.get("trocar_senha") == "1" else 0
            nova_senha = request.form.get("nova_senha", "")

            if papel not in ("superadmin", "gestor", "assistente"):
                from flask import abort

                abort(400, description="Perfil inválido.")
            if g.user["papel"] == "gestor" and papel != usuario["papel"]:
                from flask import abort

                abort(403, description="Gestor não pode alterar perfis de acesso.")
            if usuario["id"] == g.user["id"] and papel != usuario["papel"]:
                from flask import abort

                abort(403, description="Não é permitido alterar o próprio perfil de acesso.")

            # O usuário master 'administrator' não pode ter seu perfil ou status alterados
            if usuario["username"] == "administrator":
                papel = "superadmin"
                ativo = 1

            if not nome or not email:
                flash("Nome e e-mail são obrigatórios.", "danger")
                return render_template("usuarios/form.html", acao="editar", usuario=usuario)

            # Checa se email já está em uso por outro
            existente_email = identity_conflict(conn, email, exclude_id=id)
            if existente_email:
                flash("Este e-mail já está sendo utilizado por outro usuário.", "danger")
                return render_template("usuarios/form.html", acao="editar", usuario=usuario)

            if nova_senha:
                valido, msg_erro = validar_complexidade_senha(nova_senha)
                if not valido:
                    flash(msg_erro, "danger")
                    return render_template("usuarios/form.html", acao="editar", usuario=usuario)

                nova_hash = generate_password_hash(nova_senha)
                conn.execute(
                    """
                    UPDATE admin_usuarios
                    SET nome = ?, email = ?, papel = ?, ativo = ?, trocar_senha = ?, auth_version = auth_version + 1, senha_hash = ?
                    WHERE id = ?
                    """,
                    (nome, email, papel, ativo, trocar_senha, nova_hash, id),
                )
            else:
                conn.execute(
                    """
                    UPDATE admin_usuarios
                    SET nome = ?, email = ?, papel = ?, ativo = ?, trocar_senha = ?, auth_version = auth_version + 1
                    WHERE id = ?
                    """,
                    (nome, email, papel, ativo, trocar_senha, id),
                )

            audit(
                conn,
                "update",
                "usuario",
                id,
                before={k: usuario[k] for k in ("nome", "email", "papel", "ativo", "trocar_senha")},
                after={
                    "nome": nome,
                    "email": email,
                    "papel": papel,
                    "ativo": ativo,
                    "trocar_senha": trocar_senha,
                    "password_reset": bool(nova_senha),
                },
            )
            flash("Usuário atualizado com sucesso!", "success")
            return redirect(url_for("usuarios.listar"))

    return render_template("usuarios/form.html", acao="editar", usuario=usuario)


@usuarios_bp.route("/<int:id>/excluir", methods=["POST"])
@login_required
@validate_form
def excluir(id):
    if g.user["papel"] != "superadmin":
        flash("Apenas usuários com perfil Superadmin podem excluir contas de usuários.", "danger")
        return redirect(url_for("usuarios.listar"))

    with get_db() as conn:
        usuario = conn.execute(
            "SELECT id, username FROM admin_usuarios WHERE id = ?", (id,)
        ).fetchone()
        if not usuario:
            flash("Usuário não encontrado.", "danger")
            return redirect(url_for("usuarios.listar"))

        # Proteção estrita: não permitir excluir o administrator master
        if usuario["username"] == "administrator":
            flash("O usuário master 'administrator' não pode ser excluído.", "danger")
            return redirect(url_for("usuarios.listar"))

        # Proteção: não permitir autoexclusão
        if usuario["id"] == g.user["id"]:
            flash("Você não pode excluir o seu próprio usuário logado.", "danger")
            return redirect(url_for("usuarios.listar"))

        audit(conn, "delete", "usuario", id, before={"username": usuario["username"]})
        conn.execute("DELETE FROM admin_usuarios WHERE id = ?", (id,))
        flash(f"Usuário '{usuario['username']}' excluído com sucesso!", "success")

    return redirect(url_for("usuarios.listar"))
