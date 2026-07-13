import csv
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI

from models.schemas import ChatRequest, ChatResponse
from services.inventory import InventoryService
from services.llm import extract_search_filters
from services.user_memory import (
    get_user_profile,
    save_user_preferences,
)

app = FastAPI()

inventory_service = InventoryService("data/cars.xlsx")
LEADS_FILE = Path("data/leads.csv")
AVAILABLE_DAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
]
BOOKING_WORDS = [
    "book",
    "booking",
    "schedule",
    "view",
    "viewing",
    "appointment",
    "test drive",
]
POSITIONS = {
    "first": 0,
    "second": 1,
    "third": 2,
    "fourth": 3,
    "fifth": 4,
}

# Short-term conversation memory keyed by user_id.
sessions = {}


def format_car_name(car):
    """Return a compact readable name for a car listing."""
    return (
        f"{car['year']} "
        f"{car['make']} "
        f"{car['model']} "
        f"{car['trim']}"
    )


def get_requested_position(message):
    """Return the selected result index when the user says first, second, etc."""
    message_lower = message.lower()

    for word, index in POSITIONS.items():
        if word in message_lower:
            return index

    return None


def search_inventory(user_id, message, user_session):
    """Extract filters with Gemini, search inventory, and store shown results."""

    filters = extract_search_filters(message)

    results = inventory_service.search(
        make=filters.make,
        model=filters.model,
        min_year=filters.min_year,
        max_year=filters.max_year,
        max_cash_price=filters.max_cash_price,
        keywords=filters.keywords,
    )

    if results.empty:
        return (
            "I could not find any cars matching those requirements. "
            "Try broadening one of your filters."
        )
    # Save preferences only after a successful search.
    save_user_preferences(
        user_id,
        filters,
        message,
    )

    displayed_results = results.head(5)
    user_session["last_results"] = displayed_results.to_dict(
        orient="records"
    )

    reply = f"I found {len(results)} matching cars:\n\n"

    for number, (_, car) in enumerate(
        displayed_results.iterrows(),
        start=1
    ):
        reply += (
            f"{number}. {format_car_name(car)}\n"
        )

    return reply


def is_booking_request(message):
    """Return True when the user appears to want a viewing or test drive."""
    message_lower = message.lower()

    return any(
        word in message_lower
        for word in BOOKING_WORDS
    )


def create_session():
    """Create a fresh in-memory session for one user."""
    return {
        "last_results": [],
        "booking": None,
        "lead": None,
    }


def booking_in_progress(user_session):
    return user_session["booking"] is not None


def lead_in_progress(user_session):
    return user_session["lead"] is not None


def save_lead(user_id, lead):
    """Append a completed viewing lead to the CSV file."""
    file_exists = LEADS_FILE.exists()
    car = lead["car"]
    lead_data = {
        "user_id": user_id,
        "listing_id": car["Listing_ID"],
        "car": format_car_name(car),
        "budget": lead["budget"],
        "purpose": lead["purpose"],
        "phone": lead["phone"],
        "viewing_day": lead["day"],
        "viewing_time": lead["time"],
    }

    LEADS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with LEADS_FILE.open(
        mode="a",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=lead_data.keys(),
        )

        if not file_exists:
            writer.writeheader()

        writer.writerow(lead_data)


def continue_lead(user_id, message, user_session):
    """Collect budget, purpose, and phone number after a viewing is booked."""
    lead = user_session["lead"]

    if lead["budget"] is None:

        try:
            budget = int(message.replace(",", "").strip())

        except ValueError:
            return (
                "Please enter your budget as a number. "
                "For example: 150000"
            )

        lead["budget"] = budget

        return (
            "Thank you.\n\n"
            "What will you mainly use the car for?\n"
            "(For example: Family, Daily commute, Off-road)"
        )

    if lead["purpose"] is None:
        lead["purpose"] = message.strip()

        return (
            "Great.\n\n"
            "Finally, what is the best phone number "
            "to contact you?"
        )

    if lead["phone"] is None:
        lead["phone"] = message.strip()
        save_lead(
            user_id,
            lead,
        )

        user_session["lead"] = None

        return (
            "Thank you! Your details have been recorded, "
            "and the viewing request is complete."
        )


def continue_booking(message, user_session):
    """Collect viewing day and time, then start lead qualification."""
    booking = user_session["booking"]
    message_lower = message.lower()

    if booking["day"] is None:
        for day in AVAILABLE_DAYS:
            if day in message_lower:
                booking["day"] = day.title()

                return (
                    f"Great. I have saved {booking['day']}.\n\n"
                    "What time would you like to visit? "
                    "Viewings are available from 8 AM to 8 PM."
                )

        # The user did not provide a valid day
        return (
            "Please choose a day from Monday to Saturday. "
            "Viewings are not available on Sunday."
        )

    if booking["time"] is None:
        try:
            selected_time = datetime.strptime(
                message.strip().upper(),
                "%I %p",
            )

        except ValueError:
            return (
                "Please enter a time in a format such as "
                "4 PM or 10 AM."
            )

        hour = selected_time.hour

        if hour < 8 or hour > 20:
            return (
                "That time is outside the available viewing hours. "
                "Please choose a time between 8 AM and 8 PM."
            )

        booking["time"] = selected_time.strftime("%I:%M %p")
        selected_car = booking["car"]

        confirmation = (
            f"Your viewing has been booked successfully.\n\n"
            f"Car: {format_car_name(selected_car)}\n"
            f"Day: {booking['day']}\n"
            f"Time: {booking['time']}"
        )

        user_session["lead"] = {
            "car": selected_car,
            "day": booking["day"],
            "time": booking["time"],
            "budget": None,
            "purpose": None,
            "phone": None,
        }
        user_session["booking"] = None

        return (
            confirmation
            + "\n\n"
            + "Before we finish, I'd like to ask a couple short questions.\n\n"
            + "What is your budget?"
        )


def is_greeting(message):
    greetings = [
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
    ]

    return message.strip().lower() in greetings


def build_returning_user_reply(user_id, profile):
    # Build a readable summary of the user's saved preferences.
    display_name = user_id.replace("_", " ").title()

    if profile.get("search_summary"):
        return (
            f"Welcome back, {display_name}!\n\n"
            f"Last time, you were looking for "
            f"{profile['search_summary']}.\n\n"
            "Would you like to continue that search?"
        )

    preferences = []
    keywords = [
        str(keyword).lower()
        for keyword in profile.get("keywords", [])
    ]
    vehicle_label = "SUVs" if "suv" in keywords else "cars"

    if profile.get("make"):
        car_type = f"{profile['make'].title()} {vehicle_label}"

        if profile.get("model"):
            car_type = (
                f"{profile['make'].title()} "
                f"{profile['model'].title()} {vehicle_label}"
            )

        preferences.append(car_type)

    elif profile.get("model"):
        preferences.append(f"{profile['model'].title()} {vehicle_label}")

    if profile.get("min_year"):
        preferences.append(
            f"from {profile['min_year']} onwards"
        )

    if profile.get("max_year"):
        preferences.append(
            f"up to {profile['max_year']}"
        )

    if profile.get("max_cash_price"):
        preferences.append(
            f"under AED {profile['max_cash_price']:,}"
        )

    if profile.get("keywords"):
        feature_keywords = [
            keyword
            for keyword in keywords
            if keyword != "suv"
        ]

        if feature_keywords:
            preferences.append(f"with {', '.join(feature_keywords)}")

    if not preferences:
        return (
            f"Welcome back, {display_name}! "
            "How can I help with your car search today?"
        )

    return (
        f"Welcome back, {display_name}!\n\n"
        f"Last time, you were looking for: "
        f"{' '.join(preferences)}.\n\n"
        "Would you like to continue that search?"
    )


def process_message(user_id, message):
    """Route a user message through memory, booking, lead, or search flow."""
    if user_id not in sessions:
        sessions[user_id] = create_session()

    user_session = sessions[user_id]

    # Active workflows should continue before any new intent is considered.
    if lead_in_progress(user_session):
        return continue_lead(
            user_id,
            message,
            user_session,
        )

    if booking_in_progress(user_session):
        return continue_booking(
            message,
            user_session,
        )

    # Recognise a returning user when they send a greeting and no workflow is active.
    if is_greeting(message):
        profile = get_user_profile(user_id)

        if profile:
            return build_returning_user_reply(
                user_id,
                profile
            )

        return (
            f"Hello, {user_id}! "
            "What kind of car are you looking for?"
        )

    if is_booking_request(message):
        requested_position = get_requested_position(message)
        last_results = user_session["last_results"]

        if not last_results:
            return (
                "Please search for some cars before booking a viewing."
            )

        if requested_position is None:
            return (
                "Which car would you like to book? "
                "Please choose the first, second, third, fourth, or fifth car."
            )

        if requested_position >= len(last_results):
            return (
                f"I only showed you {len(last_results)} cars. "
                "Please choose one of those results."
            )

        selected_car = last_results[requested_position]
        user_session["booking"] = {
            "car": selected_car,
            "day": None,
            "time": None,
        }

        return (
            f"Great. You selected the {format_car_name(selected_car)}.\n\n"
            "What day would you like to view it? "
            "Viewings are available Monday to Saturday."
        )

    requested_position = get_requested_position(message)

    if requested_position is not None:
        last_results = user_session["last_results"]

        if not last_results:
            return (
                "I do not have any previous search results for you yet. "
                "Please search for some cars first."
            )

        if requested_position >= len(last_results):
            return (
                f"I only showed you {len(last_results)} cars. "
                "Please choose one of those results."
            )

        selected_car = last_results[requested_position]

        return (
            f"The {format_car_name(selected_car)} is listed as:\n\n"
            f"{selected_car['title']}\n\n"
            f"{selected_car['description']}"
        )

    return search_inventory(
        user_id,
        message,
        user_session,
    )


@app.get("/")
def home():
    return {
        "message": "Dubizzle AI Assistant API is running!"
    }


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    reply = process_message(
        request.user_id,
        request.message,
    )

    return ChatResponse(reply=reply)
