"""Настройки приложения.

Все параметры читаются из переменных окружения (при наличии — из файла ``.env``
в корне проекта). Секреты в код не попадают: токен бота и ключ API задаются
только через окружение. Образец переменных — в ``.env.example``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_MODEL = "claude-haiku-5-5"


@dataclass(frozen=True)
class Settings:
    """Неизменяемый набор настроек, собранный из окружения."""

    bot_token: str
    """Токен Telegram-бота от @BotFather (пустой — бот не запускается, консоль работает)."""

    operator_chat_id: int | None
    """ID чата оператора, куда пересылаются обращения вне базы знаний."""

    admin_ids: tuple[int, ...]
    """Пользователи, которым доступна команда /stats в личном чате."""

    llm_provider: str
    """``auto`` | ``anthropic`` | ``fake``. В режиме ``auto`` Claude используется при наличии ключа."""

    anthropic_api_key: str | None
    anthropic_model: str

    knowledge_dir: Path
    """Папка с файлами базы знаний ``*.md``."""

    db_path: Path
    """Файл SQLite с журналом диалогов."""

    min_overlap: float
    """Минимальная доля слов вопроса, найденных в статье базы, чтобы отдавать её модели."""

    metrics_host: str
    metrics_port: int

    company_name: str

    @property
    def has_operator_chat(self) -> bool:
        return self.operator_chat_id is not None


def _parse_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    return int(value.strip())


def _parse_int_list(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    return tuple(int(part) for part in value.replace(";", ",").split(",") if part.strip())


def load_settings(env_file: str | os.PathLike[str] | None = None) -> Settings:
    """Собрать настройки из окружения.

    :param env_file: путь к файлу ``.env``; по умолчанию ``<корень проекта>/.env``.
        Уже заданные переменные окружения имеют приоритет над файлом.
    """
    load_dotenv(env_file or BASE_DIR / ".env", override=False)

    return Settings(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        operator_chat_id=_parse_int(os.getenv("OPERATOR_CHAT_ID")),
        admin_ids=_parse_int_list(os.getenv("ADMIN_IDS")),
        llm_provider=os.getenv("LLM_PROVIDER", "auto").strip().lower(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        anthropic_model=os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        knowledge_dir=Path(os.getenv("KNOWLEDGE_DIR", BASE_DIR / "knowledge")),
        db_path=Path(os.getenv("DB_PATH", BASE_DIR / "data" / "dialogs.sqlite3")),
        min_overlap=float(os.getenv("MIN_OVERLAP", "0.3")),
        metrics_host=os.getenv("METRICS_HOST", "127.0.0.1"),
        metrics_port=int(os.getenv("METRICS_PORT", "8000")),
        company_name=os.getenv("COMPANY_NAME", "автосервис «Вектор»"),
    )
