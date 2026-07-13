from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str


class CarSearchFilters(BaseModel):
    """Structured filters extracted from a user's car search request."""

    make: str | None = None
    model: str | None = None
    min_year: int | None = None
    max_year: int | None = None
    max_cash_price: int | None = None
    keywords: list[str] = Field(default_factory=list)
