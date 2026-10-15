"""Обработчики сообщений от клиентов и от операторов.

Структура с роутерами взята из официальных примеров aiogram 3 (MIT):
``examples/echo_bot.py`` и ``examples/multi_file_bot``. Зависимости
(``assistant``, ``settings``, ``storage``) приходят в обработчики через
``workflow_data`` диспетчера — так их легко подменить в тестах.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re

from aiogram import Bot, F, Router, html as h
from aiogram.filters import BaseFilter, Command, CommandObject, CommandStart
from aiogram.types import Message

from ..assistant import Assistant
from ..config import Settings
from ..storage import STATUS_LABELS, Storage

log = logging.getLogger(__name__)

_TICKET_RE = re.compile(r"#(\d+)")

# Текст без угловых скобок: бот отправляет сообщения в режиме HTML,
# и «<номер>» Telegram принял бы за тег.
REPLY_HINT = "Формат: /reply номер текст. Пример: /reply 3 Запчасти пришли, можно записываться."

user_router = Router(name="user")
operator_router = Router(name="operator")


class OperatorChat(BaseFilter):
    """Пропускает только сообщения из чата оператора."""

    async def __call__(self, message: Message, settings: Settings) -> bool:  # type: ignore[override]
        return settings.has_operator_chat and message.chat.id == settings.operator_chat_id


class StatsAllowed(BaseFilter):
    """Кому доступна команда /stats: чат оператора, администраторы или все, если оператор не настроен."""

    async def __call__(self, message: Message, settings: Settings) -> bool:  # type: ignore[override]
        if not settings.has_operator_chat and not settings.admin_ids:
            return True
        return message.chat.id == settings.operator_chat_id or message.from_user.id in settings.admin_ids


def format_stats(stats: dict) -> str:
    """Текст сводки для команды /stats."""
    lines = [
        h.bold("Статистика обращений"),
        f"Всего: {stats['total']}",
        f"Закрыто ботом: {stats['closed_by_bot']} ({stats['bot_share']:.0%})",
        f"Передано оператору: {stats['escalated']} (отвечено: {stats['answered_by_operator']})",
    ]
    if stats["top_questions"]:
        lines.append("")
        lines.append(h.bold("Топ вопросов:"))
        for item in stats["top_questions"]:
            lines.append(f"• {html.escape(item['topic'])} — {item['count']}")
    return "\n".join(lines)


def format_escalation(ticket_id: int, message: Message) -> str:
    """Карточка обращения для чата оператора."""
    user = message.from_user
    who = html.escape(user.full_name)
    if user.username:
        who += f" (@{user.username})"
    return (
        f"🆘 Обращение #{ticket_id}\n"
        f"От: {who}, id {user.id}\n"
        f"Вопрос: {html.escape(message.text or '')}\n\n"
        f"Ответьте на это сообщение (reply) обычным текстом — он уйдёт клиенту. "
        f"Или командой: /reply {ticket_id} текст"
    )


def ticket_from_reply(message: Message) -> int | None:
    """Номер обращения из карточки, на которую оператор ответил reply-ем."""
    if message.reply_to_message is None:
        return None
    match = _TICKET_RE.search(message.reply_to_message.text or "")
    return int(match.group(1)) if match else None


# --- клиентские обработчики --------------------------------------------------


@user_router.message(CommandStart())
async def cmd_start(message: Message, assistant: Assistant) -> None:
    await message.answer(assistant.greeting())


@user_router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Напишите вопрос обычным текстом — например, «сколько стоит замена масла?» "
        "или «как записаться?». Если ответа нет в базе, вопрос получит оператор и ответит здесь же."
    )


@user_router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    """Показать id чата — его вписывают в OPERATOR_CHAT_ID при настройке."""
    await message.answer(
        f"ID этого чата: <code>{message.chat.id}</code>\nВаш user id: <code>{message.from_user.id}</code>"
    )


@user_router.message(Command("stats"), StatsAllowed())
async def cmd_stats(message: Message, storage: Storage) -> None:
    await message.answer(format_stats(storage.stats()))


@user_router.message(F.text, ~F.text.startswith("/"), F.chat.type == "private")
async def on_question(message: Message, bot: Bot, assistant: Assistant, settings: Settings) -> None:
    """Главный сценарий: ответ по базе или передача оператору."""
    user = message.from_user
    reply = await asyncio.to_thread(
        assistant.handle,
        message.text,
        user_id=user.id,
        chat_id=message.chat.id,
        username=user.username,
    )
    await message.answer(html.escape(reply.text))
    if reply.escalated:
        if settings.has_operator_chat:
            await bot.send_message(settings.operator_chat_id, format_escalation(reply.ticket_id, message))
        else:
            log.warning("OPERATOR_CHAT_ID не задан: обращение #%s не переслано", reply.ticket_id)


@user_router.message(F.chat.type == "private")
async def on_other(message: Message) -> None:
    await message.answer("Я понимаю только текстовые сообщения. Напишите вопрос словами, пожалуйста.")


# --- операторские обработчики -----------------------------------------------


async def _send_operator_answer(bot: Bot, storage: Storage, ticket_id: int, text: str) -> str:
    """Отправить ответ оператора клиенту и обновить журнал. Возвращает текст подтверждения."""
    dialog = storage.get(ticket_id)
    if dialog is None:
        return f"Обращение #{ticket_id} не найдено."
    await bot.send_message(dialog.chat_id, f"Ответ оператора:\n{html.escape(text)}")
    storage.set_operator_answer(ticket_id, text)
    return f"Ответ по обращению #{ticket_id} отправлен клиенту ({STATUS_LABELS['answered_by_operator']})."


@operator_router.message(Command("reply"), OperatorChat())
async def cmd_reply(message: Message, command: CommandObject, bot: Bot, storage: Storage) -> None:
    """``/reply номер текст`` — ответ клиенту по номеру обращения.

    Если команда отправлена reply-ем на карточку, номер можно не указывать:
    ``/reply текст`` возьмёт его из карточки.
    """
    args = (command.args or "").split(maxsplit=1)
    ticket_id = ticket_from_reply(message)
    if len(args) >= 2 and args[0].isdigit():
        ticket_id, text = int(args[0]), args[1]
    elif ticket_id is not None and args:
        text = " ".join(args)
    else:
        await message.answer(REPLY_HINT)
        return
    await message.answer(await _send_operator_answer(bot, storage, ticket_id, text))


@operator_router.message(Command("stats"), OperatorChat())
async def cmd_operator_stats(message: Message, storage: Storage) -> None:
    await message.answer(format_stats(storage.stats()))


@operator_router.message(F.reply_to_message, F.text, OperatorChat())
async def on_operator_reply(message: Message, bot: Bot, storage: Storage) -> None:
    """Ответ оператора reply-ем на карточку обращения."""
    ticket_id = ticket_from_reply(message)
    if ticket_id is None:
        await message.answer("Не вижу номера обращения в сообщении, на которое вы ответили.")
        return
    await message.answer(await _send_operator_answer(bot, storage, ticket_id, message.text))
