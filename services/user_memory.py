import json
from pathlib import Path

# File used to store returning-user preferences
USER_FILE = Path("data/users.json")


def load_users():
    """Load saved user profiles from disk."""
    if not USER_FILE.exists():
        return {}

    with USER_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_user_profile(user_id):
    """Return one saved user profile."""
    users = load_users()
    return users.get(user_id)


def has_search_preferences(filters):
    """Return True when Gemini extracted at least one useful preference."""
    return any(
        [
            filters.make,
            filters.model,
            filters.min_year,
            filters.max_year,
            filters.max_cash_price,
            filters.keywords,
        ]
    )


def add_memory_keyword(keywords, keyword):
    """Add one remembered keyword without duplicating it."""
    existing_keywords = [
        saved_keyword.lower()
        for saved_keyword in keywords
    ]

    if keyword not in existing_keywords:
        keywords.append(keyword)


def format_car_text(value):
    """Format saved make or model text for user-facing replies."""
    return str(value).replace("-", " ").title()


def build_search_summary(filters, keywords):
    """Build a short readable summary of the user's last search."""
    parts = []
    lower_keywords = [
        keyword.lower()
        for keyword in keywords
    ]
    feature_keywords = [
        keyword
        for keyword in keywords
        if keyword.lower() != "suv"
    ]
    vehicle_label = "SUVs" if "suv" in lower_keywords else "cars"

    if filters.make and filters.model:
        parts.append(
            f"{format_car_text(filters.make)} "
            f"{format_car_text(filters.model)} {vehicle_label}"
        )
    elif filters.make:
        parts.append(f"{format_car_text(filters.make)} {vehicle_label}")
    elif filters.model:
        parts.append(f"{format_car_text(filters.model)} {vehicle_label}")
    elif "suv" in lower_keywords:
        parts.append("SUVs")
    else:
        parts.append("cars")

    if filters.min_year:
        parts.append(f"from {filters.min_year} onwards")

    if filters.max_year:
        parts.append(f"up to {filters.max_year}")

    if filters.max_cash_price:
        parts.append(f"under AED {filters.max_cash_price:,}")

    if feature_keywords:
        parts.append(f"with {', '.join(feature_keywords)}")

    return " ".join(parts)


def save_user_preferences(user_id, filters, message=None):
    """Save the user's latest meaningful inventory preferences."""
    if not has_search_preferences(filters):
        return False

    users = load_users()
    keywords = list(filters.keywords)

    if message and "suv" in message.lower():
        add_memory_keyword(keywords, "suv")

    users[user_id] = {
        "make": filters.make,
        "model": filters.model,
        "min_year": filters.min_year,
        "max_year": filters.max_year,
        "max_cash_price": filters.max_cash_price,
        "keywords": keywords,
        "search_summary": build_search_summary(filters, keywords),
    }

    USER_FILE.parent.mkdir(parents=True, exist_ok=True)

    with USER_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            users,
            file,
            indent=4
        )

    return True
