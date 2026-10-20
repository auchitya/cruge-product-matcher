from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Category(str, Enum):
    SMARTPHONE = "smartphone"
    TELEVISION = "television"
    SNEAKERS = "sneakers"
    TSHIRT = "tshirt"  # t-shirts, polos and jerseys


class Status(str, Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    NOT_LISTED = "not_listed"
    ERROR = "error"  # we could not reach the platform — never silently "not listed"


class ProductSpec(BaseModel):
    """Everything we know about one product, from any platform, in one shape."""

    title: str
    brand: str | None = None
    category: Category | None = None
    model: str | None = None  # human-readable model name, e.g. "Galaxy S25"
    model_codes: list[str] = Field(default_factory=list)  # e.g. ["UA55DUE77AKLXL"]
    ram_gb: float | None = None
    storage_gb: float | None = None
    screen_inches: float | None = None
    colour: str | None = None
    gender: str | None = None  # men / women / unisex / kids — fashion only
    product_type: str | None = None  # tshirt / polo / jersey — apparel only
    kind: str | None = None  # the platform's own category label for the listing, e.g. Flipkart "mobile-panel"
    url: str | None = None
    image: str | None = None
    price: float | None = None
    in_stock: bool | None = None
    platform_id: str | None = None


class Check(BaseModel):
    """One rule the matcher evaluated, so the UI can show *why*."""

    name: str
    ok: bool
    required: bool = True  # False = a preference (e.g. phone colour); failing it doesn't reject
    source: str | None = None
    candidate: str | None = None
    note: str | None = None


class CandidateResult(BaseModel):
    spec: ProductSpec
    matched: bool
    score: float
    checks: list[Check]


class PlatformResult(BaseModel):
    platform: str
    status: Status
    match: ProductSpec | None = None
    confidence: str | None = None  # high / medium / low — how sure we are it's the same product
    checks: list[Check] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    search_query: str | None = None
    candidates_seen: int = 0
    near_misses: list[CandidateResult] = Field(default_factory=list)
    error: str | None = None
    elapsed_ms: int = 0


class MatchResponse(BaseModel):
    source: ProductSpec
    results: list[PlatformResult]
    elapsed_ms: int
