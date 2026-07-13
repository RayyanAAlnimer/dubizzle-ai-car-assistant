import csv
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI

from models.schemas import ChatRequest, ChatResponse
from services.inventory import InventoryService
from services.llm import extract_search_filters

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


def search_inventory(message, user_session):
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


def process_message(user_id, message):
    """Route a user message through memory, booking, lead, or search flow."""
    if user_id not in sessions:
        sessions[user_id] = create_session()

    user_session = sessions[user_id]

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
