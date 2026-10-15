import pytest

from support_bot.knowledge import Entry
from support_bot.search import KnowledgeSearch, stem, tokenize
from tests.conftest import CONTROL_QUESTIONS, OUT_OF_SCOPE_QUESTION


@pytest.mark.parametrize(
    "forms",
    [
        ("масло", "масла", "маслом"),
        ("записаться", "запись", "записи"),
        ("гарантия", "гарантии", "гарантию"),
        ("работы", "работаете", "работа"),
        ("цена", "цены", "цену"),
        ("шины", "шин", "шину"),
    ],
)
def test_stem_unifies_word_forms(forms: tuple[str, ...]) -> None:
    stems = {stem(form) for form in forms}
    assert len(stems) == 1, stems


def test_tokenize_drops_stopwords_and_punctuation() -> None:
    assert tokenize("Какой у вас режим работы?!") == ["режим", "работ"]
    assert tokenize("Привет") != []
    assert tokenize("???") == []


@pytest.mark.parametrize("question,expected,_", CONTROL_QUESTIONS)
def test_control_questions_hit_expected_entry(entries: list[Entry], question: str, expected: str, _: str) -> None:
    hits = KnowledgeSearch(entries).search(question)
    assert hits, question
    assert hits[0].entry.question == expected
    assert hits[0].overlap >= 0.5


def test_out_of_scope_question_has_low_overlap(entries: list[Entry]) -> None:
    hits = KnowledgeSearch(entries).search(OUT_OF_SCOPE_QUESTION)
    assert all(hit.overlap < 0.3 for hit in hits)


def test_search_returns_at_most_top_k(entries: list[Entry]) -> None:
    hits = KnowledgeSearch(entries).search("сколько стоит", top_k=2)
    assert len(hits) <= 2
    assert hits == sorted(hits, key=lambda h: h.score, reverse=True)
