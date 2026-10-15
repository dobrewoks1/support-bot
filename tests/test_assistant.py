from support_bot.assistant import ESCALATION_TEXT, Assistant
from support_bot.knowledge import Entry
from support_bot.llm import FakeProvider, LLMError, LLMReply
from support_bot.search import SearchHit
from support_bot.storage import STATUS_CLOSED, STATUS_ESCALATED, Storage
from tests.conftest import CONTROL_QUESTIONS, OUT_OF_SCOPE_QUESTION


def test_five_questions_answered_sixth_escalated(assistant: Assistant, storage: Storage) -> None:
    for question, expected_entry, must_contain in CONTROL_QUESTIONS:
        reply = assistant.handle(question, user_id=1, username="client")
        assert reply.status == STATUS_CLOSED, question
        assert reply.matched_entry == expected_entry
        assert must_contain in reply.text
        assert not reply.escalated

    reply = assistant.handle(OUT_OF_SCOPE_QUESTION, user_id=1, username="client")
    assert reply.escalated
    assert reply.text == ESCALATION_TEXT
    assert reply.ticket_id == 6

    # Журнал: шесть записей, пять закрыто ботом, одна передана оператору.
    stats = storage.stats()
    assert stats["total"] == 6
    assert stats["closed_by_bot"] == 5
    assert stats["escalated"] == 1
    last = storage.get(6)
    assert last is not None
    assert last.question == OUT_OF_SCOPE_QUESTION
    assert last.status == STATUS_ESCALATED
    assert last.username == "client"


def test_llm_not_covered_leads_to_escalation(entries: list[Entry], storage: Storage) -> None:
    question = "Сколько стоит замена масла?"
    provider = FakeProvider(scripted={question: LLMReply(answer="", covered=False, model="fake")})
    reply = Assistant(entries, provider, storage).handle(question)
    assert reply.escalated
    assert reply.matched_entry == "Сколько стоит замена масла?"  # статья нашлась, но модель её отвергла
    assert provider.calls and provider.calls[0][0] == question


def test_llm_error_falls_back_to_operator(entries: list[Entry], storage: Storage) -> None:
    class BrokenProvider:
        name = "broken"

        def answer(self, question: str, hits: list[SearchHit]) -> LLMReply:
            raise LLMError("нет сети")

    reply = Assistant(entries, BrokenProvider(), storage).handle("Какой у вас режим работы?")
    assert reply.escalated
    assert storage.get(reply.ticket_id).provider == "broken"


def test_small_talk_without_llm(assistant: Assistant, provider: FakeProvider) -> None:
    hello = assistant.handle("Привет!")
    thanks = assistant.handle("Спасибо большое")
    assert hello.status == STATUS_CLOSED and "ассистент" in hello.text
    assert thanks.status == STATUS_CLOSED
    assert provider.calls == []  # модель не вызывалась


def test_low_overlap_hits_are_not_sent_to_llm(assistant: Assistant, provider: FakeProvider) -> None:
    reply = assistant.handle(OUT_OF_SCOPE_QUESTION)
    assert reply.escalated
    assert provider.calls == []
