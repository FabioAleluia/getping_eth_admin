import re
import secrets
from flask import session, request, abort

def gerar_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]

def validar_csrf_token():
    token = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
    if not token or token != session.get("_csrf_token"):
        abort(400, description="Token CSRF inválido ou expirado.")

def validar_complexidade_senha(senha: str) -> tuple[bool, str | None]:
    """
    Valida se a senha atende aos requisitos mínimos de segurança:
    - No mínimo 8 caracteres
    - Pelo menos um caractere especial (!@#$%^&*()_+-=[]{}|;:,.<>?/ etc.)
    - Não ser a senha padrão 'administrator'
    """
    if not senha or not senha.strip():
        return False, "A nova senha não pode estar em branco."

    senha_limpa = senha.strip()
    if senha_limpa.lower() == "administrator":
        return False, "A nova senha não pode ser igual à senha padrão 'administrator'."

    if len(senha_limpa) < 8:
        return False, "A nova senha deve ter no mínimo 8 caracteres."

    if not re.search(r"[^a-zA-Z0-9\s]", senha_limpa):
        return False, "A nova senha deve conter pelo menos um caractere especial (ex: ! @ # $ % & *)."

    return True, None
