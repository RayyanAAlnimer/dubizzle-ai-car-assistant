import re

from config import GEMINI_MODEL

from dotenv import load_dotenv
from google import genai
from google.genai import types

from models.schemas import CarSearchFilters


load_dotenv()

client = None
KNOWN_MAKES = {
    "toyota": "toyota",
    "lexus": "lexus",
    "ford": "ford",
    "jaguar": "jaguar",
    "lincoln": "lincoln",
    "mercedes": "mercedes-benz",
    "mercedes-benz": "mercedes-benz",
    "land rover": "land rover",
    "rolls-royce": "rolls-royce",
    "rolls royce": "rolls-royce",
}


def get_client():
    """Create the Gemini client only when it is needed."""
    global client

    if client is None:
        client = genai.Client(
            http_options=types.HttpOptions(timeout=20_000)
        )

    return client


def add_keyword(filters, keyword):
    """Add one keyword without duplicating it."""
    existing_keywords = [
        saved_keyword.lower()
        for saved_keyword in filters.keywords
    ]

    if keyword not in existing_keywords:
        filters.keywords.append(keyword)


def apply_message_fallbacks(message, filters):
    """Fill obvious filters when Gemini returns a partial extraction."""
    message_lower = message.lower()

    if filters.make is None:
        for make_text, make_value in KNOWN_MAKES.items():
            if make_text in message_lower:
                filters.make = make_value
                break

    if filters.model is None:
        if "rav 4" in message_lower or "rav4" in message_lower:
            filters.model = "rav 4"

    if filters.min_year is None:
        min_year_match = re.search(
            r"from\s+((?:19|20)\d{2})\s+onwards",
            message_lower,
        )

        if min_year_match:
            filters.min_year = int(min_year_match.group(1))

    if filters.max_cash_price is None:
        price_match = re.search(
            r"(?:under|below|less than)\s*(?:aed\s*)?([\d,]+)",
            message_lower,
        )

        if price_match:
            filters.max_cash_price = int(
                price_match.group(1).replace(",", "")
            )

    if "warranty" in message_lower:
        add_keyword(filters, "warranty")

    if "gcc" in message_lower:
        add_keyword(filters, "gcc")

    return filters


def extract_search_filters(message):
    """Use Gemini to extract inventory search filters from a user message."""
    prompt = f"""
You extract search filters for a used-car inventory.

Read the user's message and return only the filters they clearly requested.

Rules:
- Do not invent information.
- Use null when a filter was not provided.
- Put features such as warranty, GCC, sunroof, Apple CarPlay,
  leather seats, or 7-seater inside keywords.
- If the user says "from 2020 onwards", set min_year to 2020.
- If the user says "under AED 150000", set max_cash_price to 150000.
- max_cash_price means the total cash price, not a monthly payment.
- Do not answer the user.
- Only extract search filters.

User message:
{message}
"""

    response = get_client().models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CarSearchFilters,
        ),
    )

    if isinstance(response.parsed, CarSearchFilters):
        filters = response.parsed
    elif response.parsed is not None:
        filters = CarSearchFilters.model_validate(response.parsed)
    else:
        filters = CarSearchFilters.model_validate_json(response.text)

    return apply_message_fallbacks(message, filters)
