from fastapi.testclient import TestClient

from support_bot.assistant import Assistant
from support_bot.metrics import create_app
from support_bot.storage import Storage


def test_metrics_json_and_html(assistant: Assistant, storage: Storage) -> None:
    assistant.handle("Какой у вас режим работы?", user_id=5)
    assistant.handle("Поможете оформить ОСАГО?", user_id=5)

    client = TestClient(create_app(storage))
    data = client.get("/metrics").json()
    assert data["total"] == 2
    assert data["closed_by_bot"] == 1
    assert data["escalated"] == 1
    assert data["top_questions"][0]["count"] == 1

    page = client.get("/")
    assert page.status_code == 200
    assert "Обращения в бота" in page.text
    assert "передано оператору" in page.text
    assert "Поможете оформить ОСАГО?" in page.text
