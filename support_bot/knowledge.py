"""Загрузка базы знаний из Markdown-файлов.

Формат файла (см. ``knowledge/*.md``)::

    # Заголовок раздела (игнорируется)

    ### Вопрос клиента
    Текст ответа — один или несколько абзацев.

    Теги: дополнительные, ключевые, слова

Каждый заголовок третьего уровня начинает новую статью. Строка ``Теги:`` не
попадает в ответ, но участвует в поиске.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")
_TAGS_RE = re.compile(r"^\s*Теги:\s*(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Entry:
    """Одна статья базы знаний: вопрос, ответ и теги."""

    id: str
    question: str
    answer: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    source: str = ""

    @property
    def search_text(self) -> str:
        """Текст, по которому строится поисковый индекс."""
        return "\n".join([self.question, self.answer, " ".join(self.tags)])


def parse_markdown(text: str, source: str = "") -> list[Entry]:
    """Разобрать содержимое одного Markdown-файла в список статей."""
    entries: list[Entry] = []
    question: str | None = None
    body: list[str] = []
    tags: list[str] = []

    def flush() -> None:
        if question is None:
            return
        answer = "\n".join(body).strip()
        if not answer:
            raise ValueError(f"{source}: у вопроса «{question}» нет ответа")
        entries.append(
            Entry(
                id=f"{source}#{len(entries) + 1}" if source else str(len(entries) + 1),
                question=question.strip(),
                answer=answer,
                tags=tuple(tags),
                source=source,
            )
        )

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            question, body, tags = heading.group(1), [], []
            continue
        if question is None:
            continue  # преамбула файла до первой статьи
        tags_match = _TAGS_RE.match(line)
        if tags_match:
            tags.extend(t.strip() for t in tags_match.group(1).split(",") if t.strip())
            continue
        body.append(line)
    flush()
    return entries


def load_knowledge(directory: Path) -> list[Entry]:
    """Загрузить все ``*.md`` файлы из папки (в алфавитном порядке)."""
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"Папка базы знаний не найдена: {directory}")
    entries: list[Entry] = []
    for path in sorted(directory.glob("*.md")):
        entries.extend(parse_markdown(path.read_text(encoding="utf-8"), source=path.name))
    if not entries:
        raise ValueError(f"В папке {directory} нет ни одной статьи")
    return entries
