"""Diagnóstico sem reparos: compara os objetos com as migrações distribuídas."""

import sqlite3
from contextlib import closing
from functools import lru_cache

from getping_admin.database.migrate import MIGRATIONS_PATH, SCHEMA_PATH


@lru_cache(maxsize=1)
def expected_schema():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute(
            "CREATE TABLE schema_migrations "
            "(version INTEGER PRIMARY KEY, aplicado_em TEXT NOT NULL)"
        )
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        versions = set()
        for path in sorted(MIGRATIONS_PATH.glob("*.sql")):
            conn.executescript(path.read_text(encoding="utf-8"))
            versions.add(int(path.stem.split("_")[0]))
        objects = conn.execute(
            "SELECT type,name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"
        ).fetchall()
        columns = {
            name: {row[1] for row in conn.execute(f'PRAGMA table_info("{name}")')}
            for kind, name, _ in objects
            if kind == "table"
        }
    return versions, objects, columns


def schema_issues(conn):
    versions, expected, columns = expected_schema()
    actual = {
        row["name"]: row
        for row in conn.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        )
    }
    issues = []
    if "schema_migrations" not in actual:
        issues.append("Tabela de migrações ausente.")
    elif {r[0] for r in conn.execute("SELECT version FROM schema_migrations")} != versions:
        issues.append("Migrações pendentes ou incompatíveis com esta versão.")
    for kind, name, sql in expected:
        row = actual.get(name)
        if row is None or row["type"] != kind:
            issues.append(f"Objeto ausente ou incompatível: {name}.")
        elif kind in {"index", "trigger"}:
            if " ".join(row["sql"].split()) != " ".join(sql.split()):
                issues.append(f"Definição divergente: {name}.")
        elif kind == "table":
            found = {r["name"] for r in conn.execute(f'PRAGMA table_info("{name}")')}
            if not columns[name].issubset(found):
                issues.append(f"Colunas obrigatórias ausentes: {name}.")
    return issues
