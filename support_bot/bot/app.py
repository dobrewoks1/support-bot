"""Сборка бота и запуск long polling."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from ..assistant import Assistant
from ..config import Settings
from .handlers import operator_router, user_router

log = logging.getLogger(__name__)


def build_dispatcher(settings: Settings, assistant: Assistant) -> Dispatcher:
    """Создать диспетчер с роутерами и внедрёнными зависимостями."""
    dp = Dispatcher()
    dp["settings"] = settings
    dp["assistant"] = assistant
    dp["storage"] = assistant.storage
    # Операторский роутер первым: его фильтры отсеивают всё, что не из чата оператора.
    dp.include_routers(operator_router, user_router)
    return dp


async def run_bot(settings: Settings, assistant: Assistant) -> None:
    """Запустить бота (long polling). Блокирует до остановки процесса."""
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN не задан. Для демонстрации без Telegram: python -m support_bot --console")
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher(settings, assistant)
    log.info(
        "Запуск бота: провайдер=%s, статей в базе=%d, чат оператора=%s",
        assistant.provider.name,
        len(assistant.entries),
        settings.operator_chat_id or "не задан",
    )
    await dp.start_polling(bot)
