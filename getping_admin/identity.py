"""Identificadores canônicos e namespace compartilhado de autenticação."""


def normalize_identifier(value):
    return value.strip().lower()


def identity_conflict(conn, *identifiers, exclude_id=-1):
    """Compare também com legados ainda não normalizados, sem escolher uma conta."""
    wanted = {normalize_identifier(value) for value in identifiers}
    return any(
        row["id"] != exclude_id
        and wanted.intersection(
            (normalize_identifier(row["username"]), normalize_identifier(row["email"]))
        )
        for row in conn.execute("SELECT id,username,email FROM admin_usuarios")
    )


def invalid_identity_ids(conn):
    owners = {}
    invalid = set()
    for row in conn.execute("SELECT id,username,email FROM admin_usuarios"):
        for field in ("username", "email"):
            value = row[field]
            if not isinstance(value, str):
                invalid.add(row["id"])
                continue
            normalized = normalize_identifier(value)
            if not normalized:
                invalid.add(row["id"])
            if normalized in owners and owners[normalized] != row["id"]:
                invalid.update((owners[normalized], row["id"]))
            owners[normalized] = row["id"]
    return sorted(invalid)
