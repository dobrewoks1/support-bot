"""Страница метрик на FastAPI: ``/metrics`` (JSON) и ``/`` (простой HTML).

Запуск: ``python -m support_bot --metrics`` (по умолчанию http://127.0.0.1:8000).
"""

from __future__ import annotations

import html

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .storage import STATUS_LABELS, Storage

_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>support-bot — метрики</title>
<style>
 body {{ font-family: system-ui, sans-serif; max-width: 760px; margin: 2rem auto; padding: 0 1rem; color: #222; }}
 .cards {{ display: flex; gap: 1rem; flex-wrap: wrap; }}
 .card {{ flex: 1 1 150px; border: 1px solid #ddd; border-radius: 8px; padding: 1rem; }}
 .card b {{ display: block; font-size: 1.8rem; }}
 table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
 td, th {{ border-bottom: 1px solid #eee; padding: .4rem .6rem; text-align: left; }}
 small {{ color: #666; }}
</style></head><body>
<h1>Обращения в бота</h1>
<div class="cards">
 <div class="card"><b>{total}</b>всего</div>
 <div class="card"><b>{closed}</b>закрыто ботом ({share:.0%})</div>
 <div class="card"><b>{escalated}</b>передано оператору</div>
 <div class="card"><b>{answered}</b>отвечено оператором</div>
</div>
<h2>Топ вопросов</h2>
<table><tr><th>Тема</th><th>Сколько раз</th></tr>{top_rows}</table>
<h2>Последние обращения</h2>
<table><tr><th>#</th><th>Вопрос</th><th>Статус</th></tr>{recent_rows}</table>
<p><small>JSON: <a href="/metrics">/metrics</a></small></p>
</body></html>"""


def create_app(storage: Storage) -> FastAPI:
    """Фабрика приложения — удобно для тестов с собственным хранилищем."""
    app = FastAPI(title="support-bot metrics", version="0.1.0")

    @app.get("/metrics")
    def metrics() -> dict:
        return storage.stats()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        stats = storage.stats()
        top_rows = "".join(
            f"<tr><td>{html.escape(i['topic'])}</td><td>{i['count']}</td></tr>" for i in stats["top_questions"]
        ) or "<tr><td colspan=2>пока пусто</td></tr>"
        recent_rows = "".join(
            f"<tr><td>{d.id}</td><td>{html.escape(d.question)}</td>"
            f"<td>{STATUS_LABELS.get(d.status, d.status)}</td></tr>"
            for d in storage.recent(10)
        ) or "<tr><td colspan=3>пока пусто</td></tr>"
        return _PAGE.format(
            total=stats["total"],
            closed=stats["closed_by_bot"],
            share=stats["bot_share"],
            escalated=stats["escalated"],
            answered=stats["answered_by_operator"],
            top_rows=top_rows,
            recent_rows=recent_rows,
        )

    return app


def run_metrics(storage: Storage, host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(create_app(storage), host=host, port=port)
