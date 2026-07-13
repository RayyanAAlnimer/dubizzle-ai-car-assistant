from fastapi.testclient import TestClient

import main
from models.schemas import CarSearchFilters
from services.inventory import InventoryService
from services.llm import apply_message_fallbacks
import services.user_memory as user_memory


def patch_gemini_filters(monkeypatch, filters):
    def fake_extract_search_filters(message):
        return filters

    monkeypatch.setattr(
        main,
        "extract_search_filters",
        fake_extract_search_filters,
    )
    monkeypatch.setattr(
        main,
        "save_user_preferences",
        lambda user_id, filters, message=None: None,
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


def test_message_fallbacks_fill_partial_search_filters():
    filters = apply_message_fallbacks(
        "Show me Toyota SUVs from 2020 onwards under AED 150000 with warranty",
        CarSearchFilters(max_cash_price=150000),
    )

    assert filters.make == "toyota"
    assert filters.min_year == 2020
    assert filters.max_cash_price == 150000
    assert filters.keywords == ["warranty"]


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


def test_complete_second_result_booking_continues_lead_flow(
    monkeypatch,
    tmp_path,
):
    main.sessions.clear()
    monkeypatch.setattr(
        main,
        "LEADS_FILE",
        tmp_path / "leads.csv",
    )
    patch_gemini_filters(
        monkeypatch,
        CarSearchFilters(keywords=["warranty", "gcc"]),
    )

    client = TestClient(main.app)
    user_id = "demo-user-test"

    search_response = client.post(
        "/chat",
        json={
            "user_id": user_id,
            "message": "Find cars with warranty and GCC specs",
        },
    )
    detail_response = client.post(
        "/chat",
        json={
            "user_id": user_id,
            "message": "Tell me about the second one",
        },
    )
    booking_response = client.post(
        "/chat",
        json={
            "user_id": user_id,
            "message": "Book the second one",
        },
    )
    day_response = client.post(
        "/chat",
        json={
            "user_id": user_id,
            "message": "Tuesday",
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
            "message": "0500000000",
        },
    )

    assert search_response.status_code == 200
    assert "I found" in search_response.json()["reply"]
    assert detail_response.status_code == 200
    assert "is listed as" in detail_response.json()["reply"]
    assert booking_response.status_code == 200
    assert (
        "What day would you like to view it?"
        in booking_response.json()["reply"]
    )
    assert day_response.status_code == 200
    assert "What time would you like to visit?" in day_response.json()["reply"]
    assert time_response.status_code == 200
    assert "What is your budget?" in time_response.json()["reply"]
    assert budget_response.status_code == 200
    assert (
        "What will you mainly use the car for?"
        in budget_response.json()["reply"]
    )
    assert purpose_response.status_code == 200
    assert "best phone number" in purpose_response.json()["reply"]
    assert "I found" not in purpose_response.json()["reply"]
    assert phone_response.status_code == 200
    assert "viewing request is complete" in phone_response.json()["reply"]
    assert "I found" not in phone_response.json()["reply"]
    assert main.sessions[user_id]["booking"] is None
    assert main.sessions[user_id]["lead"] is None

    leads_csv = (tmp_path / "leads.csv").read_text(encoding="utf-8")
    assert user_id in leads_csv
    assert "Tuesday" in leads_csv
    assert "04:00 PM" in leads_csv
    assert "150000" in leads_csv
    assert "Family" in leads_csv
    assert "0500000000" in leads_csv


def test_returning_user_recall_survives_new_session(monkeypatch, tmp_path):
    main.sessions.clear()
    monkeypatch.setattr(
        user_memory,
        "USER_FILE",
        tmp_path / "users.json",
    )
    monkeypatch.setattr(
        main,
        "save_user_preferences",
        user_memory.save_user_preferences,
    )
    monkeypatch.setattr(
        main,
        "get_user_profile",
        user_memory.get_user_profile,
    )
    monkeypatch.setattr(
        main,
        "extract_search_filters",
        lambda message: CarSearchFilters(
            make="toyota",
            min_year=2020,
            max_cash_price=150000,
            keywords=["warranty"],
        ),
    )

    client = TestClient(main.app)
    user_id = "rayyan"

    search_response = client.post(
        "/chat",
        json={
            "user_id": user_id,
            "message": (
                "Show me Toyota SUVs from 2020 onwards "
                "under AED 150000 with warranty"
            ),
        },
    )
    assert search_response.status_code == 200
    assert "I found" in search_response.json()["reply"]

    # Simulate restarting Uvicorn: short-term sessions are gone,
    # but data/users.json remains.
    main.sessions.clear()

    greeting_response = client.post(
        "/chat",
        json={
            "user_id": user_id,
            "message": "Hi",
        },
    )

    assert greeting_response.status_code == 200
    reply = greeting_response.json()["reply"]
    assert "Welcome back, Rayyan!" in reply
    assert "Toyota SUVs" in reply
    assert "from 2020 onwards" in reply
    assert "under AED 150,000" in reply
    assert "with warranty" in reply

    profile = user_memory.get_user_profile(user_id)
    assert (
        profile["search_summary"]
        == "Toyota SUVs from 2020 onwards under AED 150,000 with warranty"
    )


def test_empty_filters_do_not_overwrite_saved_preferences(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        user_memory,
        "USER_FILE",
        tmp_path / "users.json",
    )

    user_memory.save_user_preferences(
        "rayyan",
        CarSearchFilters(
            make="toyota",
            min_year=2020,
            max_cash_price=150000,
            keywords=["warranty"],
        ),
    )
    user_memory.save_user_preferences(
        "rayyan",
        CarSearchFilters(),
    )

    profile = user_memory.get_user_profile("rayyan")
    assert profile["make"] == "toyota"
    assert profile["min_year"] == 2020
    assert profile["max_cash_price"] == 150000
    assert profile["keywords"] == ["warranty"]
    assert (
        profile["search_summary"]
        == "Toyota cars from 2020 onwards under AED 150,000 with warranty"
    )
