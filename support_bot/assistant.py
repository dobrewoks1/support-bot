"""Ядро ассистента: поиск по базе → LLM → ответ или передача оператору.

Логика одинакова для Telegram и консоли:

1. Приветствия и благодарности закрываются шаблонным ответом без модели.
2. По вопросу ищутся статьи базы знаний (BM25). Статьи с долей совпавших слов
   ниже порога ``min_overlap`` отбрасываются — модели не отдают явный мусор.
3. Если подходящих статей нет — обращение сразу передаётся оператору.
4. Иначе модель отвечает строго по найденным статьям и сообщает, покрыт ли
   вопрос базой. Если нет — обращение тоже передаётся оператору.
5. Каждое обращение записывается в журнал SQLite.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .config import Settings
from .knowledge import Entry, load_knowledge
from .llm import LLMError, LLMProvider, create_provider
from .search import KnowledgeSearch, SearchHit
from .storage import STATUS_CLOSED, STATUS_ESCALATED, Storage

log = logging.getLogger(__name__)

ESCALATION_TEXT = (
    "Я не нашёл точного ответа в базе знаний, поэтому передаю ваш вопрос оператору. "
    "Ответим в этом чате в ближайшее время."
)

_GREETINGS = ("привет", "здравствуй", "добрый день", "добрый вечер", "доброе утро", "hello", "hi")
_THANKS = ("спасибо", "благодарю", "спс", "thanks")
_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)


@dataclass(frozen=True)
class Reply:
    """Результат обработки обращения."""

    text: str
    status: str
    ticket_id: int
    matched_entry: str | None
    score: float
    provider: str
    hits: tuple[SearchHit, ...] = ()

    @property
    def escalated(self) -> bool:
        return self.status == STATUS_ESCALATED


class Assistant:
    """Связывает базу знаний, поиск, провайдера LLM и журнал."""

    def __init__(
        self,
        entries: list[Entry],
        provider: LLMProvider,
        storage: Storage,
        *,
        min_overlap: float = 0.3,
        top_k: int = 3,
        company_name: str = "автосервис «Вектор»",
    ) -> None:
        self.entries = entries
        self.search = KnowledgeSearch(entries)
        self.provider = provider
        self.storage = storage
        self.min_overlap = min_overlap
        self.top_k = top_k
        self.company_name = company_name

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        provider: LLMProvider | None = None,
        storage: Storage | None = None,
        provider_override: str | None = None,
    ) -> "Assistant":
        """Собрать ассистента из настроек окружения."""
        return cls(
            entries=load_knowledge(settings.knowledge_dir),
            provider=provider or create_provider(settings, provider_override),
            storage=storage or Storage(settings.db_path),
            min_overlap=settings.min_overlap,
            company_name=settings.company_name,
        )

    # --- вспомогательные тексты -------------------------------------------------

    def greeting(self) -> str:
        return (
            f"Здравствуйте! Я ассистент компании {self.company_name}. "
            "Задайте вопрос об услугах, ценах, режиме работы, гарантии или записи — "
            "отвечу по базе знаний, а если не найду ответа, передам оператору."
        )

    @staticmethod
    def _small_talk(question: str) -> str | None:
        """Шаблонный ответ на приветствие или благодарность, иначе ``None``."""
        normalized = _PUNCT_RE.sub(" ", question.lower().replace("ё", "е")).split()
        if not normalized or len(normalized) > 4:
            return None
        text = " ".join(normalized)
        if any(text.startswith(g) for g in _GREETINGS):
            return "greeting"
        if any(text.startswith(t) for t in _THANKS):
            return "thanks"
        return None

    # --- основной сценарий ------------------------------------------------------

    def handle(
        self,
        question: str,
        *,
        user_id: int = 0,
        chat_id: int | None = None,
        username: str | None = None,
    ) -> Reply:
        """Обработать одно обращение и записать его в журнал."""
        question = question.strip()
        chat_id = user_id if chat_id is None else chat_id

        kind = self._small_talk(question)
        if kind == "greeting":
            return self._close(question, self.greeting(), "приветствие", 0.0, user_id, chat_id, username)
        if kind == "thanks":
            return self._close(
                question, "Пожалуйста! Если появятся вопросы — пишите.", "благодарность", 0.0, user_id, chat_id, username
            )

        hits = [h for h in self.search.search(question, top_k=self.top_k) if h.overlap >= self.min_overlap]
        if not hits:
            return self._escalate(question, None, 0.0, user_id, chat_id, username, hits=[])

        try:
            reply = self.provider.answer(question, hits)
        except LLMError as exc:
            log.error("LLM недоступна, передаю оператору: %s", exc)
            return self._escalate(question, hits[0].entry.question, hits[0].score, user_id, chat_id, username, hits)

        if reply.covered and reply.answer:
            return self._close(
                question, reply.answer, hits[0].entry.question, hits[0].score, user_id, chat_id, username, hits
            )
        return self._escalate(question, hits[0].entry.question, hits[0].score, user_id, chat_id, username, hits)

    def _close(
        self,
        question: str,
        answer: str,
        matched: str | None,
        score: float,
        user_id: int,
        chat_id: int,
        username: str | None,
        hits: list[SearchHit] | None = None,
    ) -> Reply:
        ticket_id = self.storage.log(
            user_id=user_id,
            chat_id=chat_id,
            username=username,
            question=question,
            answer=answer,
            status=STATUS_CLOSED,
            matched_entry=matched,
            score=score,
            provider=self.provider.name,
        )
        return Reply(answer, STATUS_CLOSED, ticket_id, matched, score, self.provider.name, tuple(hits or ()))

    def _escalate(
        self,
        question: str,
        matched: str | None,
        score: float,
        user_id: int,
        chat_id: int,
        username: str | None,
        hits: list[SearchHit],
    ) -> Reply:
        ticket_id = self.storage.log(
            user_id=user_id,
            chat_id=chat_id,
            username=username,
            question=question,
            answer=ESCALATION_TEXT,
            status=STATUS_ESCALATED,
            matched_entry=matched,
            score=score,
            provider=self.provider.name,
        )
        return Reply(ESCALATION_TEXT, STATUS_ESCALATED, ticket_id, matched, score, self.provider.name, tuple(hits))
