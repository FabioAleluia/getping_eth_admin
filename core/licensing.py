# All timestamps in the existing database contract are UTC.
# Alias names are internal constants, never derived from user input.
def effective_status(license_alias='l', client_alias='c'):
    return f"""CASE
        WHEN {client_alias}.ativo != 1 THEN 'suspensa'
        WHEN {license_alias}.status != 'ativa' THEN {license_alias}.status
        WHEN datetime({license_alias}.data_expiracao) IS NULL THEN 'invalida'
        WHEN {license_alias}.data_expiracao < datetime('now') THEN 'expirada'
        ELSE 'ativa' END"""
