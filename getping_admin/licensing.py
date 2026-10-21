"""Regras compartilhadas de licenciamento."""

import secrets
from datetime import datetime

from flask import current_app


def valid_license_limits(hosts, agents):
    return (
        type(hosts) is int and type(agents) is int and 1 <= hosts <= 10000 and 0 <= agents <= 10000
    )


def invalid_license_ids(conn):
    invalid = []
    for row in conn.execute("SELECT id,limite_hosts,limite_agentes,data_expiracao FROM licencas"):
        try:
            datetime.strptime(row["data_expiracao"], "%Y-%m-%d %H:%M:%S")
            if not valid_license_limits(row["limite_hosts"], row["limite_agentes"]):
                raise ValueError()
        except (ValueError, TypeError):
            invalid.append(row["id"])
    return invalid


# All timestamps in the existing database contract are UTC.
# Alias names are internal constants, never derived from user input.
def effective_status(license_alias="l", client_alias="c"):
    return f"""CASE
        WHEN {client_alias}.ativo != 1 THEN 'suspensa'
        WHEN {license_alias}.status != 'ativa' THEN {license_alias}.status
        WHEN datetime({license_alias}.data_expiracao) IS NULL THEN 'invalida'
        WHEN {license_alias}.data_expiracao < datetime('now') THEN 'expirada'
        ELSE 'ativa' END"""


def gerar_chave_licenca():
    # Keep the legacy key shape unless the client has been verified for longer keys.
    size = 4 if current_app.config["EXTENDED_LICENSE_KEYS"] else 2
    return "GPING-" + "-".join(secrets.token_hex(size).upper() for _ in range(4))
