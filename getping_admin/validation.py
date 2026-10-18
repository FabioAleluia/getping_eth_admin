import re
from datetime import datetime
from functools import wraps

from flask import abort, request

PLANS = {"Trial", "Basico", "Profissional", "Enterprise"}
STATUSES = {"ativa", "suspensa", "expirada", "cancelada"}


def text(data, name, default="", maximum=255, required=False):
    value = data.get(name, default)
    if not isinstance(value, str):
        abort(400, description=f"{name}: informe texto.")
    value = value.strip()
    if len(value) > maximum or (required and not value):
        abort(400, description=f"{name}: valor vazio ou maior que {maximum} caracteres.")
    return value


def integer(data, name, default, minimum, maximum):
    raw = data.get(name, default)
    if isinstance(raw, bool) or not re.fullmatch(r"-?\d{1,10}", str(raw)):
        abort(400, description=f"{name}: informe um número inteiro.")
    value = int(raw)
    if not minimum <= value <= maximum:
        abort(400, description=f"{name}: use um valor entre {minimum} e {maximum}.")
    return value


def choice(data, name, default, allowed):
    value = text(data, name, default)
    if value not in allowed:
        abort(400, description=f"{name}: opção inválida.")
    return value


def expiration(value):
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError()
        datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        abort(400, description="Data de expiração inválida.")
    # Preserve the existing UTC contract. UI and documentation explicitly label UTC.
    return value + " 23:59:59"


def validate_form_fields():
    if request.method != "POST" or request.blueprint == "api":
        return
    limits = {
        "observacoes": 4000,
        "telefone": 40,
        "cnpj_cpf": 25,
        "username": 100,
        "nome_empresa": 200,
        "nome": 200,
        "responsavel_nome": 200,
        "email": 254,
        "responsavel_email": 254,
    }
    for name, maximum in limits.items():
        if name in request.form:
            value = text(request.form, name, maximum=maximum)
            if (
                name in {"email", "responsavel_email"}
                and value
                and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value)
            ):
                abort(400, description="E-mail inválido.")
    for name in ("senha", "senha_inicial", "senha_atual", "nova_senha", "confirma_senha"):
        if len(request.form.get(name, "")) > 256:
            abort(400, description="Senha maior que 256 caracteres.")


def validate_form(view):
    """Valida os campos enviados pelo formulário desta view antes da mutação."""

    @wraps(view)
    def validated(*args, **kwargs):
        validate_form_fields()
        return view(*args, **kwargs)

    return validated
