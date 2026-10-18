from flask import Blueprint, render_template

from getping_admin.auth import login_required
from getping_admin.database.db import get_db
from getping_admin.licensing import effective_status

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    with get_db() as conn:
        total_clientes = conn.execute("SELECT COUNT(*) as total FROM clientes").fetchone()["total"]
        total_licencas = conn.execute("SELECT COUNT(*) as total FROM licencas").fetchone()["total"]
        licencas_ativas = conn.execute(
            f"SELECT COUNT(*) as total FROM licencas l JOIN clientes c ON c.id=l.cliente_id WHERE ({effective_status()})='ativa'"
        ).fetchone()["total"]
        licencas_expiradas = conn.execute(
            f"SELECT COUNT(*) as total FROM licencas l JOIN clientes c ON c.id=l.cliente_id WHERE ({effective_status()})='expirada'"
        ).fetchone()["total"]

        ultimas_licencas = conn.execute(
            f"""
            SELECT l.*, {effective_status()} AS status_efetivo, c.nome_empresa
            FROM licencas l
            JOIN clientes c ON l.cliente_id = c.id
            ORDER BY l.id DESC
            LIMIT 5
            """
        ).fetchall()

        ultimos_logs = conn.execute(
            """
            SELECT lg.*, l.tipo_plano, c.nome_empresa
            FROM licenca_logs lg
            LEFT JOIN licencas l ON lg.licenca_id = l.id
            LEFT JOIN clientes c ON l.cliente_id = c.id
            ORDER BY lg.id DESC
            LIMIT 8
            """
        ).fetchall()

    return render_template(
        "dashboard/index.html",
        total_clientes=total_clientes,
        total_licencas=total_licencas,
        licencas_ativas=licencas_ativas,
        licencas_expiradas=licencas_expiradas,
        ultimas_licencas=[dict(r, status=r["status_efetivo"]) for r in ultimas_licencas],
        ultimos_logs=ultimos_logs,
    )
