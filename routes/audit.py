import json
from flask import Blueprint, abort, g, render_template, request
from database.db import get_db
from routes.auth import login_required
from core.validation import text, integer
from core.pagination import page_parameters, page_rows

audit_bp = Blueprint('audit', __name__, url_prefix='/auditoria')


@audit_bp.get('/')
@login_required
def listar():
    if g.user['papel'] != 'superadmin':
        abort(403, description='Apenas superadmin pode consultar a auditoria.')
    limit, offset = page_parameters()
    action = text(request.args, 'acao', maximum=64)
    entity = text(request.args, 'entidade', maximum=64)
    actor = text(request.args, 'ator', maximum=20)
    clauses, params = [], []
    for column, value in (('a.action', action), ('a.entity', entity)):
        if value:
            clauses.append(f'{column}=?')
            params.append(value)
    if actor:
        actor_id = integer(request.args, 'ator', 0, 1, 2147483647)
        clauses.append('a.actor_id=?')
        params.append(actor_id)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    with get_db() as conn:
        rows = conn.execute('''SELECT a.*, u.username as actor_name FROM admin_audit a
            LEFT JOIN admin_usuarios u ON u.id=a.actor_id''' + where +
            ' ORDER BY a.id DESC LIMIT ? OFFSET ?', [*params, limit, offset]).fetchall()
    events = []
    for row in page_rows(rows):
        event = dict(row)
        for field in ('before_json', 'after_json'):
            try:
                event[field] = json.dumps(json.loads(event[field] or 'null'), ensure_ascii=False, indent=2)
            except (ValueError, TypeError):
                event[field] = 'Registro legado em formato inválido.'
        events.append(event)
    return render_template('audit/listar.html', events=events, acao=action, entidade=entity, ator=actor)
