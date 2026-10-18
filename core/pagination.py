from flask import request, g, url_for
from core.validation import integer


def page_parameters():
    page = integer(request.args, 'pagina', 1, 1, 100000)
    g.page = page
    g.page_size = 50
    return g.page_size + 1, (page - 1) * g.page_size


def page_rows(rows):
    g.has_next = len(rows) > g.page_size
    return rows[:g.page_size]


def pagination_context():
    if not hasattr(g, 'page'):
        return {}
    args = {key:request.args[key] for key in ('busca','status') if key in request.args}
    def link(page):
        return url_for(request.endpoint, **dict(args, pagina=page))
    return {'page_number': g.page, 'previous_page': link(g.page-1) if g.page > 1 else None,
            'next_page': link(g.page+1) if getattr(g,'has_next',False) else None}
