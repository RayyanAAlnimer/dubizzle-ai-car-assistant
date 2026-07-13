from fastapi.testclient import TestClient

import main
from models.schemas import CarSearchFilters
from services.inventory import InventoryService


def test_inventory_search_filters_by_make_and_keyword():
    inventory = InventoryService("data/cars.xlsx")

    results = inventory.search(
        make="land rover",
        keywords=["warranty"],
    )

    assert not results.empty
    assert set(results["make"].str.lower()) == {"land rover"}
    assert results["searchable_text"].str.contains(
        "warranty",
        case=False,
        regex=False,
    ).all()


def test_chat_endpoint_uses_search_filters_without_real_gemini(monkeypatch):
    main.sessions.clear()

    def fake_extract_search_filters(message):
        return CarSearchFilters(keywords=["warranty"])

    monkeypatch.setattr(
        main,
        "extract_search_filters",
        fake_extract_search_filters,
    )

    client = TestClient(main.app)

    response = client.post(
        "/chat",
        json={
            "user_id": "test-user",
            "message": "Find cars with warranty",
        },
    )

    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "I found" in reply
    assert main.sessions["test-user"]["last_results"]


def test_chat_endpoint_uses_conversation_memory(monkeypatch):
    main.sessions.clear()

    def fake_extract_search_filters(message):
        return CarSearchFilters(keywords=["warranty"])

    monkeypatch.setattr(
        main,
        "extract_search_filters",
        fake_extract_search_filters,
    )

    client = TestClient(main.app)

    search_response = client.post(
        "/chat",
        json={
            "user_id": "test-user",
            "message": "Find cars with warranty",
        },
    )
    assert search_response.status_code == 200

    detail_response = client.post(
        "/chat",
        json={
            "user_id": "test-user",
            "message": "Tell me more about the first one",
        },
    )

    assert detail_response.status_code == 200
    assert "is listed as" in detail_response.json()["reply"]
