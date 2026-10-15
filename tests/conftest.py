"""Общие фикстуры. Все тесты работают без ключа API и без сети."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from support_bot.assistant import Assistant
from support_bot.knowledge import Entry, load_knowledge
from support_bot.llm import FakeProvider
from support_bot.storage import Storage

ROOT = Path(__file__).resolve().parent.parent

# Пять контрольных вопросов, на которые бот обязан ответить из базы, и ожидаемая статья.
CONTROL_QUESTIONS: list[tuple[str, str, str]] = [
    ("Сколько стоит замена масла?", "Сколько стоит замена масла?", "900"),
    ("Какой у вас режим работы?", "Какой у вас режим работы?", "9:00"),
    ("Где вы находитесь?", "Где вы находитесь?", "Тестовая"),
    ("Какая гарантия на работы?", "Какая гарантия на работы?", "6 месяцев"),
    ("Как записаться на обслуживание?", "Как записаться на обслуживание?", "тремя способами"),
]

# Шестой вопрос — вне базы знаний: должен уйти оператору.
OUT_OF_SCOPE_QUESTION = "Поможете оформить ОСАГО?"


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Гарантия, что тесты не уйдут в сеть, даже если ключ есть в окружении."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "fake")


@pytest.fixture(scope="session")
def entries() -> list[Entry]:
    return load_knowledge(ROOT / "knowledge")


@pytest.fixture
def storage() -> Storage:
    return Storage(":memory:")


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def assistant(entries: list[Entry], storage: Storage, provider: FakeProvider) -> Assistant:
    return Assistant(entries, provider, storage)


@pytest.fixture
def project_env() -> dict[str, str]:
    """Окружение для запуска CLI в подпроцессе."""
    env = dict(os.environ)
    env.update({"PYTHONIOENCODING": "utf-8", "LLM_PROVIDER": "fake"})
    env.pop("ANTHROPIC_API_KEY", None)
    return env
