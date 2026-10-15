from pathlib import Path

from support_bot.storage import STATUS_CLOSED, STATUS_ESCALATED, STATUS_OPERATOR, Storage


def _fill(storage: Storage) -> None:
    for i in range(3):
        storage.log(user_id=1, chat_id=1, username="a", question="Сколько стоит масло?", answer="900",
                    status=STATUS_CLOSED, matched_entry="Сколько стоит замена масла?", score=10.0, provider="fake")
    storage.log(user_id=2, chat_id=2, username="b", question="Где вы?", answer="...", status=STATUS_CLOSED,
                matched_entry="Где вы находитесь?", score=6.0, provider="fake")
    storage.log(user_id=3, chat_id=3, username=None, question="ОСАГО?", answer="передаю", status=STATUS_ESCALATED)


def test_stats_and_operator_answer(storage: Storage) -> None:
    _fill(storage)
    stats = storage.stats()
    assert stats["total"] == 5
    assert stats["closed_by_bot"] == 4
    assert stats["escalated"] == 1
    assert stats["answered_by_operator"] == 0
    assert stats["top_questions"][0] == {"topic": "Сколько стоит замена масла?", "count": 3}
    assert stats["bot_share"] == 0.8

    updated = storage.set_operator_answer(5, "Оформлением ОСАГО не занимаемся.")
    assert updated is not None and updated.status == STATUS_OPERATOR
    assert updated.operator_answer.startswith("Оформлением")
    assert storage.stats()["answered_by_operator"] == 1
    assert storage.stats()["escalated"] == 1  # отвеченные оператором остаются в «переданных»
    assert storage.set_operator_answer(999, "x") is None


def test_file_storage_persists(tmp_path: Path) -> None:
    db = tmp_path / "sub" / "dialogs.sqlite3"
    ticket = Storage(db).log(user_id=1, chat_id=1, username=None, question="q", answer="a", status=STATUS_CLOSED)
    assert ticket == 1
    assert Storage(db).get(1).question == "q"
    assert [d.id for d in Storage(db).recent()] == [1]
