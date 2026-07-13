from config import GEMINI_MODEL

from dotenv import load_dotenv
from google import genai
from google.genai import types

from models.schemas import CarSearchFilters


# Load the Gemini API key from .env
load_dotenv()


# Create the Gemini client with a finite timeout so SDK/network issues fail fast.
client = genai.Client(
    http_options=types.HttpOptions(timeout=20_000)
)


def extract_search_filters(message):
    # Explain Gemini's limited responsibility
    prompt = f"""
You extract search filters for a used-car inventory.

Read the user's message and return only the filters they clearly requested.

Rules:
- Do not invent information.
- Use null when a filter was not provided.
- Put features such as warranty, GCC, sunroof, SUV,
  Apple CarPlay, leather seats, or 7-seater inside keywords.
- max_cash_price means the total cash price, not a monthly payment.
- Do not answer the user.
- Only extract search filters.

User message:
{message}
"""

    # Ask Gemini to return JSON matching CarSearchFilters
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CarSearchFilters,
        ),
    )

    # Prefer the SDK's parsed Pydantic output, with text fallback for older behavior.
    if isinstance(response.parsed, CarSearchFilters):
        filters = response.parsed
    elif response.parsed is not None:
        filters = CarSearchFilters.model_validate(response.parsed)
    else:
        filters = CarSearchFilters.model_validate_json(response.text)

    return filters
