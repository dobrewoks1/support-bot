"""Точка входа: ``python -m support_bot [--console | --ask ВОПРОС | --metrics]``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .assistant import Assistant
from .config import load_settings
from .console import ask_once, run_console
from .metrics import run_metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m support_bot",
        description="Telegram-ассистент автосервиса «Вектор». Без аргументов запускает бота (long polling).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--console", action="store_true", help="чат в терминале без Telegram")
    mode.add_argument("--ask", metavar="ВОПРОС", help="задать один вопрос и выйти")
    mode.add_argument("--metrics", action="store_true", help="запустить страницу метрик (FastAPI)")
    parser.add_argument(
        "--provider", choices=["auto", "anthropic", "fake"], help="провайдер LLM (по умолчанию из LLM_PROVIDER)"
    )
    parser.add_argument("--db", help="путь к SQLite-журналу (по умолчанию из DB_PATH)")
    parser.add_argument("-v", "--verbose", action="store_true", help="подробные логи")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    settings = load_settings()
    if args.db:
        settings = settings.__class__(**{**settings.__dict__, "db_path": args.db})

    if args.metrics:
        from .storage import Storage

        run_metrics(Storage(settings.db_path), settings.metrics_host, settings.metrics_port)
        return 0

    assistant = Assistant.from_settings(settings, provider_override=args.provider)
    if args.console:
        run_console(assistant)
        return 0
    if args.ask:
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
        ask_once(assistant, args.ask)
        return 0

    from .bot.app import run_bot

    asyncio.run(run_bot(settings, assistant))
    return 0


if __name__ == "__main__":
    sys.exit(main())
