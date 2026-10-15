import re
from types import SimpleNamespace

from support_bot.bot.handlers import REPLY_HINT, _TICKET_RE, format_escalation, format_stats, ticket_from_reply


def test_operator_texts_are_safe_for_html_mode() -> None:
    """Бот шлёт сообщения в режиме HTML: сырые угловые скобки Telegram отвергает."""
    card = format_escalation(3, SimpleNamespace(text="вопрос", from_user=SimpleNamespace(full_name="Иван", username=None, id=1)))
    for text in (REPLY_HINT, card):
        assert not re.search(r"<(?!/?(b|i|code|pre|a)\b)", text), text


def test_ticket_from_reply() -> None:
    card = SimpleNamespace(text="🆘 Обращение #42\nВопрос: ...")
    assert ticket_from_reply(SimpleNamespace(reply_to_message=card)) == 42
    assert ticket_from_reply(SimpleNamespace(reply_to_message=SimpleNamespace(text="без номера"))) is None
    assert ticket_from_reply(SimpleNamespace(reply_to_message=None)) is None


def test_format_escalation_contains_ticket_and_reply_hint() -> None:
    message = SimpleNamespace(
        text="Поможете оформить <ОСАГО>?",
        from_user=SimpleNamespace(full_name="Иван Тестовый", username="ivan_test", id=42),
    )
    card = format_escalation(7, message)
    assert "#7" in card
    assert "@ivan_test" in card
    assert "&lt;ОСАГО&gt;" in card  # HTML экранирован
    assert "/reply 7" in card
    assert _TICKET_RE.search(card).group(1) == "7"


def test_format_stats_lists_top_questions() -> None:
    text = format_stats(
        {
            "total": 10,
            "closed_by_bot": 8,
            "escalated": 2,
            "answered_by_operator": 1,
            "bot_share": 0.8,
            "top_questions": [{"topic": "Сколько стоит замена масла?", "count": 4}],
            "top_escalated": [],
        }
    )
    assert "Всего: 10" in text
    assert "80%" in text
    assert "Сколько стоит замена масла? — 4" in text
