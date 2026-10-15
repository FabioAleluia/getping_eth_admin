from datetime import datetime, timezone
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import check_password_hash, generate_password_hash
from database.db import get_db
from core.security import validar_complexidade_senha

auth_bp = Blueprint("auth", __name__)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Por favor, faça login para acessar esta página.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return decorated_function


@auth_bp.before_app_request
def carregar_usuario_logado():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        with get_db() as conn:
            g.user = conn.execute(
                "SELECT id, nome, username, email, papel, ativo, trocar_senha FROM admin_usuarios WHERE id = ?",
                (user_id,)
            ).fetchone()
            if g.user and not g.user["ativo"]:
                session.clear()
                g.user = None

    # Se o usuário logado precisa obrigatoriamente trocar a senha
    if g.user and g.user["trocar_senha"]:
        # Permite apenas a tela de troca obrigatória, logout e arquivos estáticos
        endpoint = request.endpoint or ""
        if endpoint not in ("auth.trocar_senha_obrigatoria", "auth.logout", "static"):
            return redirect(url_for("auth.trocar_senha_obrigatoria"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        senha = request.form.get("senha", "")

        if not username or not senha:
            flash("Preencha o usuário e a senha.", "danger")
            return render_template("auth/login.html")

        with get_db() as conn:
            user = conn.execute(
                "SELECT * FROM admin_usuarios WHERE username = ? OR email = ?",
                (username, username)
            ).fetchone()

            if user and user["ativo"] and check_password_hash(user["senha_hash"], senha):
                session.clear()
                session["user_id"] = user["id"]
                session.permanent = True
                from core.security import gerar_csrf_token
                gerar_csrf_token()

                agora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "UPDATE admin_usuarios SET ultimo_login = ? WHERE id = ?",
                    (agora, user["id"])
                )

                next_url = request.args.get("next")
                if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                    return redirect(next_url)
                return redirect(url_for("dashboard.index"))
            else:
                flash("Credenciais inválidas ou conta inativa.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/perfil", methods=["GET", "POST"])
@login_required
def perfil():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip()
        senha_atual = request.form.get("senha_atual", "")
        nova_senha = request.form.get("nova_senha", "")
        confirma_senha = request.form.get("confirma_senha", "")

        if not nome or not email:
            flash("Nome e e-mail são obrigatórios.", "danger")
            return render_template("auth/perfil.html")

        with get_db() as conn:
            # Checa se email já está em uso por outro
            existente = conn.execute(
                "SELECT id FROM admin_usuarios WHERE email = ? AND id != ?",
                (email, g.user["id"])
            ).fetchone()
            if existente:
                flash("Este e-mail já está sendo utilizado por outro administrador.", "danger")
                return render_template("auth/perfil.html")

            if nova_senha:
                user = conn.execute(
                    "SELECT senha_hash FROM admin_usuarios WHERE id = ?",
                    (g.user["id"],)
                ).fetchone()

                if not check_password_hash(user["senha_hash"], senha_atual):
                    flash("Senha atual incorreta.", "danger")
                    return render_template("auth/perfil.html")

                valido, msg_erro = validar_complexidade_senha(nova_senha)
                if not valido:
                    flash(msg_erro, "danger")
                    return render_template("auth/perfil.html")

                if nova_senha != confirma_senha:
                    flash("A confirmação de senha não confere.", "danger")
                    return render_template("auth/perfil.html")

                nova_hash = generate_password_hash(nova_senha)
                conn.execute(
                    "UPDATE admin_usuarios SET nome = ?, email = ?, senha_hash = ?, trocar_senha = 0 WHERE id = ?",
                    (nome, email, nova_hash, g.user["id"])
                )
            else:
                conn.execute(
                    "UPDATE admin_usuarios SET nome = ?, email = ? WHERE id = ?",
                    (nome, email, g.user["id"])
                )

            flash("Perfil atualizado com sucesso!", "success")
            return redirect(url_for("auth.perfil"))

    return render_template("auth/perfil.html")


@auth_bp.route("/primeiro-acesso", methods=["GET", "POST"])
@login_required
def trocar_senha_obrigatoria():
    # Se o usuário já trocou a senha, não precisa ficar nesta tela
    if g.user and not g.user["trocar_senha"]:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        nova_senha = request.form.get("nova_senha", "")
        confirma_senha = request.form.get("confirma_senha", "")

        valido, msg_erro = validar_complexidade_senha(nova_senha)
        if not valido:
            flash(msg_erro, "danger")
            return render_template("auth/trocar_senha_obrigatoria.html")

        if nova_senha != confirma_senha:
            flash("A confirmação de senha não confere.", "danger")
            return render_template("auth/trocar_senha_obrigatoria.html")

        nova_hash = generate_password_hash(nova_senha)
        with get_db() as conn:
            conn.execute(
                "UPDATE admin_usuarios SET senha_hash = ?, trocar_senha = 0 WHERE id = ?",
                (nova_hash, g.user["id"])
            )

        return redirect(url_for("dashboard.index"))

    return render_template("auth/trocar_senha_obrigatoria.html")
