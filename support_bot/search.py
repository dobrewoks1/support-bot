"""Поиск по базе знаний без внешних сервисов: BM25 поверх простого стеммера.

Подход заимствован из проекта levtmn/telegramRAG (MIT): ``rank_bm25`` +
регулярное выражение для токенов. Добавлены упрощённое отсечение русских
окончаний (чтобы «записаться», «запись» и «записи» считались одним словом),
стоп-слова и метрика ``overlap`` — доля значимых слов вопроса, найденных в статье.
Она нужна, чтобы не отдавать модели заведомо нерелевантные статьи.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from .knowledge import Entry

_TOKEN_RE = re.compile(r"[а-яa-z0-9]+")

STOPWORDS: frozenset[str] = frozenset(
    """
    а и у в на по ли к с не что как это для есть мне я бы до из о об от или же да нет
    вас ваш ваша ваше вашей вашего вашем вы вам нас наш мы мой моя мою меня можно
    ну вот так там тут если когда где кто чем при под за над его ее её их им они он она оно
    быть был была было будет бывает еще ещё уже тоже также очень про
    какой какая какое какие каков хочу хотел хотела хотелось нужно надо подскажите скажите
    пожалуйста интересует вопрос здравствуйте добрый день
    """.split()
)

# Окончания отсекаются по порядку: сначала длинные. Однобуквенное окончание
# снимается, если остаётся не меньше 3 букв («цены» → «цен»), более длинное —
# если остаётся не меньше 4 («масла» → «масл», а не «мас»). Второй проход срезает
# остаточную гласную («работа» → «работ»), чтобы совпадали формы слова.
_SUFFIXES: tuple[str, ...] = (
    "иями", "ями", "ами", "ией", "иях", "иям", "ого", "его", "ому", "ему", "ыми", "ими",
    "ешь", "ишь", "ете", "ите", "ует", "уют", "ять", "ить", "ать", "еть", "уть",
    "ала", "ила", "ыла", "ось", "ась",
    "ия", "ию", "ии", "ие", "ые", "ое", "ее", "ая", "яя", "ую", "юю", "ой", "ый", "ий",
    "ов", "ев", "ей", "ам", "ям", "ах", "ях", "ом", "ем", "ат", "ят", "ет", "ут", "ют", "ит",
    "ло", "ла", "ли", "ть", "ся", "сь",
    "а", "я", "ы", "и", "е", "о", "у", "ю", "ь", "й",
)


_REFLEXIVE = ("ся", "сь")


def stem(word: str) -> str:
    """Грубое отсечение окончаний русского слова (достаточно для поиска по FAQ)."""
    for _ in range(2):
        changed = False
        for suffix in _SUFFIXES:
            if not word.endswith(suffix):
                continue
            rest = len(word) - len(suffix)
            # Возвратное «-ся/-сь» снимаем только у длинных слов: «записаться» → «записать»,
            # но «запись» остаётся как есть.
            minimum = 5 if suffix in _REFLEXIVE else (3 if len(suffix) == 1 else 4)
            if rest >= minimum:
                word = word[:rest]
                changed = True
                break
        if not changed:
            break
    return word


def tokenize(text: str) -> list[str]:
    """Нормализовать текст: нижний регистр, ё→е, только буквы и цифры, стемминг, без стоп-слов."""
    words = _TOKEN_RE.findall(text.lower().replace("ё", "е"))
    return [stem(w) for w in words if w not in STOPWORDS and len(w) > 1]


@dataclass(frozen=True)
class SearchHit:
    """Результат поиска: статья, оценка BM25 и доля совпавших слов запроса."""

    entry: Entry
    score: float
    overlap: float


class KnowledgeSearch:
    """Индекс BM25 по статьям базы знаний.

    Вопрос и теги статьи добавляются в документ дважды — так совпадение с
    формулировкой вопроса весит больше, чем случайное слово из ответа.
    """

    def __init__(self, entries: list[Entry]) -> None:
        if not entries:
            raise ValueError("Пустая база знаний")
        self.entries = list(entries)
        self._docs: list[list[str]] = []
        self._doc_sets: list[frozenset[str]] = []
        for entry in self.entries:
            tokens = (
                tokenize(entry.question) * 2
                + tokenize(" ".join(entry.tags)) * 2
                + tokenize(entry.answer)
            )
            self._docs.append(tokens)
            self._doc_sets.append(frozenset(tokens))
        self._bm25 = BM25Okapi(self._docs)

    def search(self, query: str, top_k: int = 3) -> list[SearchHit]:
        """Вернуть до ``top_k`` статей с положительной оценкой, лучшие — первыми."""
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        scores = self._bm25.get_scores(query_tokens)
        unique = set(query_tokens)
        ranked = sorted(range(len(self.entries)), key=lambda i: scores[i], reverse=True)
        hits: list[SearchHit] = []
        for i in ranked[:top_k]:
            if scores[i] <= 0:
                break
            overlap = len(unique & self._doc_sets[i]) / len(unique)
            hits.append(SearchHit(entry=self.entries[i], score=float(scores[i]), overlap=overlap))
        return hits
