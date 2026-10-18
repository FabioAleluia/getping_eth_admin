"""Autenticação e ciclo de vida da sessão do painel."""

import math
from functools import wraps
from time import time

from flask import current_app, flash, g, redirect, request, session, url_for

from getping_admin.database.db import get_db


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.user:
            flash("Por favor, faça login para acessar esta página.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)

    return decorated_function


def carregar_usuario_logado():
    if request.blueprint == "api" or request.endpoint == "health":
        g.user = None
        return
    user_id = session.get("user_id")
    if user_id is not None:
        now = time()
        issued = session.get("issued_at")
        seen = session.get("last_seen")
        valid_times = all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in (issued, seen)
        )
        if (
            not valid_times
            or not issued <= seen <= now
            or now - issued >= current_app.config["SESSION_ABSOLUTE_SECONDS"]
            or now - seen >= current_app.config["SESSION_IDLE_SECONDS"]
        ):
            session.clear()
            user_id = None
        elif request.endpoint != "static":
            session["last_seen"] = now
    if user_id is None:
        g.user = None
    else:
        with get_db() as conn:
            g.user = conn.execute(
                "SELECT id, nome, username, email, papel, ativo, trocar_senha, auth_version FROM admin_usuarios WHERE id = ?",
                (user_id,),
            ).fetchone()
            if (
                not g.user
                or not g.user["ativo"]
                or session.get("auth_version") != g.user["auth_version"]
            ):
                session.clear()
                g.user = None

    # Se o usuário logado precisa obrigatoriamente trocar a senha
    if g.user and g.user["trocar_senha"]:
        # Permite apenas a tela de troca obrigatória, logout e arquivos estáticos
        endpoint = request.endpoint or ""
        if endpoint not in ("auth.trocar_senha_obrigatoria", "auth.logout", "static"):
            return redirect(url_for("auth.trocar_senha_obrigatoria"))
