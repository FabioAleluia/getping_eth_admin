"""Eventos de auditoria gravados na transação da operação."""

import json
from datetime import datetime, timezone

from flask import g, has_request_context, request


def audit(conn, action, entity, entity_id, before=None, after=None, *, actor_id=None):
    # Callers supply safe field sets, never full user rows or credentials.
    actor = actor_id
    if actor is None and has_request_context() and getattr(g, "user", None):
        actor = g.user["id"]
    ip = request.remote_addr if has_request_context() else None
    conn.execute(
        """INSERT INTO admin_audit
        (actor_id,action,entity,entity_id,before_json,after_json,ip_origem,criado_em)
        VALUES (?,?,?,?,?,?,?,?)""",
        (
            actor,
            action,
            entity,
            str(entity_id),
            json.dumps(before, ensure_ascii=False),
            json.dumps(after, ensure_ascii=False),
            ip,
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
