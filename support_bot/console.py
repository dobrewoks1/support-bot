"""Консольный режим: тот же ассистент, но чат в терминале, без Telegram.

Нужен для демонстрации и отладки: ``python -m support_bot --console``.
Команды: ``/stats`` — сводка, ``/exit`` — выход. Передача оператору
имитируется строкой «→ оператору: обращение #N».
"""

from __future__ import annotations

import sys

from .assistant import Assistant

PROMPT = "вы > "
BOT = "бот > "


def _stats_text(assistant: Assistant) -> str:
    stats = assistant.storage.stats()
    lines = [
        f"Всего обращений: {stats['total']}",
        f"Закрыто ботом: {stats['closed_by_bot']} ({stats['bot_share']:.0%})",
        f"Передано оператору: {stats['escalated']}",
    ]
    if stats["top_questions"]:
        lines.append("Топ вопросов:")
        lines.extend(f"  • {item['topic']} — {item['count']}" for item in stats["top_questions"])
    return "\n".join(lines)


def ask_once(assistant: Assistant, question: str, out=None) -> None:
    """Задать один вопрос и напечатать ответ (используется и в интерактивном цикле)."""
    out = out or sys.stdout
    reply = assistant.handle(question, user_id=0, username="console")
    print(f"{BOT}{reply.text}", file=out)
    if reply.escalated:
        print(f"      → оператору: обращение #{reply.ticket_id}", file=out)
    elif reply.matched_entry and reply.score:
        print(f"      [статья: «{reply.matched_entry}», score={reply.score:.1f}]", file=out)


def run_console(assistant: Assistant) -> None:
    """Интерактивный цикл чтения вопросов из stdin."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    print(f"Консольный режим. Провайдер: {assistant.provider.name}. Статей в базе: {len(assistant.entries)}.")
    print("Команды: /stats — статистика, /exit — выход.\n")
    print(f"{BOT}{assistant.greeting()}")
    while True:
        try:
            line = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in {"/exit", "/quit", "exit", "quit"}:
            break
        if line == "/stats":
            print(_stats_text(assistant))
            continue
        ask_once(assistant, line)
