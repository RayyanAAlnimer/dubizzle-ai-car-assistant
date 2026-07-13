from fastapi.testclient import TestClient

import main
from models.schemas import CarSearchFilters
from services.inventory import InventoryService


def patch_gemini_filters(monkeypatch, filters):
    def fake_extract_search_filters(message):
        return filters

    monkeypatch.setattr(
        main,
        "extract_search_filters",
        fake_extract_search_filters,
    )


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
    patch_gemini_filters(
        monkeypatch,
        CarSearchFilters(keywords=["warranty"]),
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
    patch_gemini_filters(
        monkeypatch,
        CarSearchFilters(keywords=["warranty"]),
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


def test_booking_flow_starts_from_numbered_result(monkeypatch):
    main.sessions.clear()
    patch_gemini_filters(
        monkeypatch,
        CarSearchFilters(keywords=["warranty"]),
    )

    client = TestClient(main.app)

    search_response = client.post(
        "/chat",
        json={
            "user_id": "booking-user",
            "message": "Find cars with warranty",
        },
    )
    assert search_response.status_code == 200

    booking_response = client.post(
        "/chat",
        json={
            "user_id": "booking-user",
            "message": "Book the first one",
        },
    )

    assert booking_response.status_code == 200
    assert (
        "What day would you like to view it?"
        in booking_response.json()["reply"]
    )
    assert main.sessions["booking-user"]["booking"] is not None


def test_booking_and_lead_are_saved_to_csv(monkeypatch, tmp_path):
    main.sessions.clear()
    monkeypatch.setattr(
        main,
        "LEADS_FILE",
        tmp_path / "leads.csv",
    )
    patch_gemini_filters(
        monkeypatch,
        CarSearchFilters(keywords=["warranty"]),
    )

    client = TestClient(main.app)
    user_id = "lead-user"

    client.post(
        "/chat",
        json={
            "user_id": user_id,
            "message": "Find cars with warranty",
        },
    )
    client.post(
        "/chat",
        json={
            "user_id": user_id,
            "message": "Book the first one",
        },
    )
    day_response = client.post(
        "/chat",
        json={
            "user_id": user_id,
            "message": "Monday",
        },
    )
    time_response = client.post(
        "/chat",
        json={
            "user_id": user_id,
            "message": "4 PM",
        },
    )
    budget_response = client.post(
        "/chat",
        json={
            "user_id": user_id,
            "message": "150000",
        },
    )
    purpose_response = client.post(
        "/chat",
        json={
            "user_id": user_id,
            "message": "Family",
        },
    )
    phone_response = client.post(
        "/chat",
        json={
            "user_id": user_id,
            "message": "+971500000000",
        },
    )

    assert day_response.status_code == 200
    assert time_response.status_code == 200
    assert (
        "Your viewing has been booked successfully."
        in time_response.json()["reply"]
    )
    assert budget_response.status_code == 200
    assert purpose_response.status_code == 200
    assert phone_response.status_code == 200
    assert "Your details have been recorded" in phone_response.json()["reply"]
    assert main.sessions[user_id]["booking"] is None
    assert main.sessions[user_id]["lead"] is None

    leads_csv = (tmp_path / "leads.csv").read_text(encoding="utf-8")
    assert (
        "user_id,listing_id,car,budget,purpose,phone,viewing_day,viewing_time"
        in leads_csv
    )
    assert user_id in leads_csv
    assert "150000" in leads_csv
