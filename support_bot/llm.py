"""Провайдеры LLM: Claude через SDK ``anthropic`` и детерминированная заглушка.

Оба провайдера получают вопрос клиента и найденные статьи базы знаний и
возвращают структурированный ответ: ``covered`` (есть ли ответ в выдержках)
и ``answer`` (текст для клиента). Заглушка (``FakeProvider``) нужна для тестов и
демонстрации без ключа API: она отвечает текстом лучшей статьи, если совпадение
достаточно уверенное.

Ответ Claude запрашивается в формате JSON по схеме (structured outputs,
``client.messages.parse`` + Pydantic-модель), чтобы признак «вопрос покрыт базой»
был надёжным, а не угадывался по тексту.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

from .config import DEFAULT_MODEL, Settings
from .search import SearchHit

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Ошибка обращения к модели (сеть, лимиты, неверный ключ)."""


@dataclass(frozen=True)
class LLMReply:
    """Ответ провайдера."""

    answer: str
    covered: bool
    model: str


class LLMProvider(Protocol):
    """Интерфейс провайдера: любой объект с именем и методом ``answer``."""

    name: str

    def answer(self, question: str, hits: list[SearchHit]) -> LLMReply: ...


class AnswerSchema(BaseModel):
    """Схема структурированного ответа модели."""

    covered: bool = Field(
        description="true, если ответ на вопрос полностью следует из выдержек базы знаний; "
        "false, если выдержки не содержат ответа или вопрос не о компании"
    )
    answer: str = Field(
        description="Ответ клиенту на русском языке (1–4 предложения). Пустая строка, если covered=false"
    )


SYSTEM_PROMPT = """Ты — вежливый ассистент компании {company}. Ты отвечаешь клиентам в Telegram.

Правила:
1. Отвечай ТОЛЬКО на основе выдержек из базы знаний, которые даны в сообщении. Не придумывай цены, адреса, сроки, условия и услуги, которых нет в выдержках.
2. Если выдержки не содержат ответа на вопрос, ответ есть лишь частично или вопрос не относится к компании — верни covered=false и пустой answer. Такой вопрос передадут живому оператору.
3. Если ответ есть — верни covered=true и answer: 1–4 предложения, обращение на «вы», без приветствий и подписи. Можно переформулировать выдержку, но нельзя добавлять новые факты.
4. Пиши на русском языке."""

USER_TEMPLATE = """Выдержки из базы знаний:
{context}

Вопрос клиента: {question}"""


def build_context(hits: list[SearchHit]) -> str:
    """Собрать блок выдержек для промпта."""
    parts = []
    for i, hit in enumerate(hits, 1):
        parts.append(f"[{i}] Вопрос: {hit.entry.question}\nОтвет: {hit.entry.answer}")
    return "\n---\n".join(parts) if parts else "(ничего не найдено)"


def build_user_prompt(question: str, hits: list[SearchHit]) -> str:
    return USER_TEMPLATE.format(context=build_context(hits), question=question.strip())


class AnthropicProvider:
    """Настоящий провайдер: Claude через официальный SDK."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        company_name: str = "автосервис «Вектор»",
        max_tokens: int = 2048,
    ) -> None:
        import anthropic  # импорт здесь, чтобы заглушка работала без установленного SDK

        self._anthropic = anthropic
        # api_key=None — SDK сам возьмёт ANTHROPIC_API_KEY из окружения.
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=60.0)
        self.model = model
        self.max_tokens = max_tokens
        self.system_prompt = SYSTEM_PROMPT.format(company=company_name)

    def answer(self, question: str, hits: list[SearchHit]) -> LLMReply:
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=[{"role": "user", "content": build_user_prompt(question, hits)}],
                output_format=AnswerSchema,
                # Ответ короткий и по готовому контексту — минимального усилия модели достаточно.
                output_config={"effort": "low"},
            )
        except self._anthropic.APIConnectionError as exc:
            raise LLMError(f"нет связи с API: {exc}") from exc
        except self._anthropic.APIStatusError as exc:
            raise LLMError(f"ошибка API {exc.status_code}: {exc.message}") from exc

        if response.stop_reason == "refusal":
            log.warning("Модель отказалась отвечать: %s", response.stop_details)
            return LLMReply(answer="", covered=False, model=self.model)

        parsed = response.parsed_output
        if parsed is None:
            log.warning("Структурированный ответ не получен (stop_reason=%s)", response.stop_reason)
            return LLMReply(answer="", covered=False, model=self.model)
        return LLMReply(answer=parsed.answer.strip(), covered=bool(parsed.covered), model=self.model)


class FakeProvider:
    """Заглушка без сети: детерминированные ответы для тестов и демонстрации.

    Если лучшая найденная статья покрывает не меньше ``min_overlap`` слов вопроса,
    возвращается её ответ; иначе — «не покрыто». Через ``scripted`` можно задать
    ответ на конкретный вопрос (например, чтобы проверить эскалацию по решению модели).
    """

    name = "fake"

    def __init__(self, min_overlap: float = 0.5, scripted: dict[str, LLMReply] | None = None) -> None:
        self.min_overlap = min_overlap
        self.scripted = scripted or {}
        self.calls: list[tuple[str, list[SearchHit]]] = []

    def answer(self, question: str, hits: list[SearchHit]) -> LLMReply:
        self.calls.append((question, hits))
        if question in self.scripted:
            return self.scripted[question]
        if hits and hits[0].overlap >= self.min_overlap:
            return LLMReply(answer=hits[0].entry.answer, covered=True, model="fake")
        return LLMReply(answer="", covered=False, model="fake")


def create_provider(settings: Settings, override: str | None = None) -> LLMProvider:
    """Выбрать провайдера по настройкам.

    ``fake`` — заглушка; ``anthropic`` — Claude (нужен ключ); ``auto`` — Claude при
    наличии ключа, иначе заглушка с предупреждением в логе.
    """
    choice = (override or settings.llm_provider or "auto").lower()
    if choice == "fake":
        return FakeProvider()
    if choice == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMError("LLM_PROVIDER=anthropic, но переменная ANTHROPIC_API_KEY не задана")
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            company_name=settings.company_name,
        )
    if choice == "auto":
        if settings.anthropic_api_key:
            return AnthropicProvider(
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_model,
                company_name=settings.company_name,
            )
        log.warning("ANTHROPIC_API_KEY не задан — используется фейковый провайдер (ответы из базы без LLM)")
        return FakeProvider()
    raise LLMError(f"Неизвестный провайдер: {choice!r} (ожидается auto, anthropic или fake)")
