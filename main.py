import csv
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from models.schemas import ChatRequest, ChatResponse
from services.inventory import InventoryService
from services.llm import extract_search_filters

# Load environment variables from .env
load_dotenv()

# Create the FastAPI application
app = FastAPI()

# Load the inventory once when the server starts
inventory_service = InventoryService("data/cars.xlsx")

# Store temp. conversation memory for each user
sessions = {}

def get_requested_position(message):
    # Connect position words to Python list indexes
    positions = {
        "first": 0,
        "second": 1, 
        "third": 2,
        "fourth": 3,
        "fifth": 4,
    }

    message_lower = message.lower()

    # Check whether the user referred to one of the displayed cars
    for word, index in positions.items():
        if word in message_lower:
            # Make sure the car exists in the prev. results
            return index
    
    # Return nothing if no valid position was mentioned
    return None

def search_inventory(message, user_session):
    """
    Uses Gemini to extract search filters,
    searches the inventory,
    stores the results,
    and returns a response.
    """

    # Use Gemini to understand the user's request
    filters = extract_search_filters(message)

    # Search the inventory
    results = inventory_service.search(
        make=filters.make,
        model=filters.model,
        min_year=filters.min_year,
        max_year=filters.max_year,
        max_cash_price=filters.max_cash_price,
        keywords=filters.keywords,
    )

    # No matching cars
    if results.empty:
        return (
            "I could not find any cars matching those requirements. "
            "Try broadening one of your filters."
        )

    # Store only the first five cars
    displayed_results = results.head(5)

    user_session["last_results"] = displayed_results.to_dict(
        orient="records"
    )

    # Build the reply
    reply = f"I found {len(results)} matching cars:\n\n"

    for number, (_, car) in enumerate(
        displayed_results.iterrows(),
        start=1
    ):
        reply += (
            f"{number}. "
            f"{car['year']} "
            f"{car['make']} "
            f"{car['model']} "
            f"{car['trim']}\n"
        )

    return reply

def is_booking_request(message):
    # Words that indicate the user wants to book a viewing
    booking_words = [
        "book",
        "booking",
        "schedule",
        "view",
        "viewing",
        "appointment",
        "test drive",
    ]

    message_lower = message.lower()

    # Return True if any booking word appears in the message
    return any(
        word in message_lower
        for word in booking_words
    )

def create_session():
    # Create a new session for a user
    return {
        # Cars shown in the most recent search
        "last_results": [],
        # Booking info.
        "booking": None,
        # Lead qualification info.
        "lead": None,
    }

def booking_in_progress(user_session):
    # A booking is active when booking information exists
    return user_session["booking"] is not None

def lead_in_progress(user_session):
    # A lead is active when lead info. exists
    return user_session["lead"] is not None

def save_lead(user_id, lead):
    file_path = Path("data/leads.csv")
    
    # Check if the file exists
    file_exists = file_path.exists()

    # Get the selected car
    car = lead["car"]

    # Create a readable car name
    car_name = (
        f"{car['year']}"
        f"{car['make']}"
        f"{car['model']}"
        f"{car['trim']}"
    )

    # Info. to store in the csv file
    lead_data = {
        "user_id": user_id,
        "listing_id": car["Listing_ID"],
        "car": car_name,
        "budget": lead["budget"],
        "purpose": lead["purpose"],
        "phone": lead["phone"],
        "viewing_day": lead["day"],
        "viewing_time": lead["time"],
    }

    # Open the file in append mode
    with file_path.open(
        mode="a",
        newline="",
        encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=lead_data.keys()
        )

        # Add column names only when creating the file
        if not file_exists:
            writer.writeheader()

        # Add the completed lead as a new row
        writer.writerow(lead_data)

def continue_lead(user_id, message, user_session):
    # Get the current lead
    lead = user_session["lead"]

    # Ask for the budget first
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

    # Ask for the intended purpose
    if lead["purpose"] is None:

        lead["purpose"] = message.strip()

        return (
            "Great.\n\n"
            "Finally, what is the best phone number "
            "to contact you?"
        )
    
    # Ask for the phone number
    if lead["phone"] is None:

        lead["phone"] = message.strip()

        # Save the completed lead to the csv file
        save_lead(
            user_id,
            lead
        )

        # Clear the lead workflow after saving
        user_session["lead"] = None

        return (
            "Thank you! your details have been recorded, "
            "and the viewing request is complete."
        )

def continue_booking(message, user_session):
    # Get the current booking information
    booking = user_session["booking"]

    # Days when car viewings are available
    available_days = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
    ]

    message_lower = message.lower()

    # The booking does not have a day yet
    if booking["day"] is None:
        # Check whether the user mentioned an available day
        for day in available_days:
            if day in message_lower:
                # Save the selected day
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

    # The booking has a day, so now expect a time
    if booking["time"] is None:
        try:
            # Convert input such as "4 PM" into a time object
            selected_time = datetime.strptime(
                message.strip().upper(),
                "%I %p"
            )

        except ValueError:
            return (
                "Please enter a time in a format such as "
                "4 PM or 10 AM."
            )

        # Get the hour in 24-hour format
        hour = selected_time.hour

        # Viewings are available from 8 AM to 8 PM
        if hour < 8 or hour > 20:
            return (
                "That time is outside the available viewing hours. "
                "Please choose a time between 8 AM and 8 PM."
            )

        # Save the formatted time
        booking["time"] = selected_time.strftime("%I:%M %p")

        # Get the selected car
        selected_car = booking["car"]

        # Store the confirmation before clearing the booking
        confirmation = (
            f"Your viewing has been booked successfully.\n\n"
            f"Car: {selected_car['year']} "
            f"{selected_car['make']} "
            f"{selected_car['model']}\n"
            f"Day: {booking['day']}\n"
            f"Time: {booking['time']}"
        )

        # Start collecting lead info.
        user_session["lead"] = {
            "car": selected_car,
            "day": booking["day"],
            "time": booking["time"],
            "budget": None,
            "purpose": None,
            "phone": None,
        }
        # Booking is complete
        user_session["booking"] = None

        return (
            confirmation
            + "\n\n"
            + "Before we finish, I'd like to ask a couple short questions.\n\n"
            + "What is your budget?"
        )

def process_message(user_id, message):
    # Create memory for the user if this is their first message
    if user_id not in sessions:
        sessions[user_id] = create_session()
    
    # Get the user's stored session
    user_session = sessions[user_id]

    # Continue an existing lead qualification
    if lead_in_progress(user_session):
        return continue_lead(
            user_id,
            message,
            user_session
        )

    # Continue an existing booking before handling new requests
    if booking_in_progress(user_session):
        return continue_booking(
            message,
            user_session
        )
    
    # Check whether the user wants to book a viewing
    if is_booking_request(message):
        requested_position = get_requested_position(message)
        last_results = user_session["last_results"]

        # The user has not searched for cars yet
        if not last_results:
            return (
                "Please search for some cars before booking a viewing."
            )

        # The user did not specify which displayed car they want
        if requested_position is None:
            return (
                "Which car would you like to book? "
                "Please choose the first, second, third, fourth, or fifth car."
            )

        # The requested position does not exist
        if requested_position >= len(last_results):
            return (
                f"I only showed you {len(last_results)} cars. "
                "Please choose one of those results."
            )

        # Get the selected car
        selected_car = last_results[requested_position]

        # Start the booking and store the selected car
        user_session["booking"] = {
            "car": selected_car,
            "day": None,
            "time": None,
        }

        return (
            f"Great. You selected the "
            f"{selected_car['year']} "
            f"{selected_car['make']} "
            f"{selected_car['model']}.\n\n"
            "What day would you like to view it? "
            "Viewings are available Monday to Saturday."
        )

    # Check if the user mentioned a result position
    requested_position = get_requested_position(message)

    # The user refers to a previously shown car
    if requested_position is not None:
        last_results = user_session["last_results"]

        # The user has not performed a search yet
        if not last_results:
            return (
                "I do not have any previous search results for you yet. "
                "Please search for some cars first."
            )
        
        # Requested position is outside the displayed results
        if requested_position >= len(last_results):
            return (
                f"I only showed you {len(last_results)} cars. "
                "Please choose one of those results."
            )
        
        # Retrieve the requested car
        selected_car = last_results[requested_position]

        return (
            f"The {selected_car['year']} "
            f"{selected_car['make']} "
            f"{selected_car['model']} "
            f"{selected_car['trim']} is listed as:\n\n"
            f"{selected_car['title']}\n\n"
            f"{selected_car['description']}"
        )
    
    # Perform a new inventory search
    return search_inventory(
        message,
        user_session
    )


@app.get("/")
def home():
    # Simple endpoint to check that the API is running
    return {
        "message": "Dubizzle AI Assistant API is running!"
        }

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    # Pass the user's message to the chatbot logic
    reply = process_message(
        request.user_id,
        request.message
    )

    return ChatResponse(reply=reply)
