from support_bot.knowledge import Entry, parse_markdown


def test_knowledge_base_size_and_fields(entries: list[Entry]) -> None:
    assert 25 <= len(entries) <= 60
    for entry in entries:
        assert entry.question.endswith("?"), entry.question
        assert len(entry.answer) > 20, entry.question
        assert entry.source.endswith(".md")
    assert len({e.question for e in entries}) == len(entries), "вопросы должны быть уникальными"


def test_parse_markdown_tags_and_preamble() -> None:
    text = """# Раздел
преамбула, которая игнорируется

### Первый вопрос?
Ответ один.
Вторая строка ответа.

Теги: один, два

### Второй вопрос?
Ответ два.
"""
    parsed = parse_markdown(text, source="x.md")
    assert [e.question for e in parsed] == ["Первый вопрос?", "Второй вопрос?"]
    assert parsed[0].answer == "Ответ один.\nВторая строка ответа."
    assert parsed[0].tags == ("один", "два")
    assert parsed[1].tags == ()
    assert parsed[0].id == "x.md#1"
