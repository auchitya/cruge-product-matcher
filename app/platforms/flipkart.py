"""Flipkart: server-rendered search page with the full result list in window.__INITIAL_STATE__."""
from __future__ import annotations

import re
import time
from urllib.parse import parse_qs, urlparse

from .. import http
from ..models import Category, ProductSpec
from ..normalize import (
    find_colour_in_title, garment_type, model_codes, parse_gender, parse_ram_gb, parse_screen_inches, parse_storage_gb,
)
from .base import Platform, dedupe, embedded_json

BASE = "https://www.flipkart.com"


def _image(media: dict | None) -> str | None:
    imgs = (media or {}).get("images") or []
    if not imgs:
        return None
    return imgs[0].get("url", "").replace("{@width}", "416").replace("{@height}", "416").replace("{@quality}", "70")


def _kind(v: dict) -> str | None:
    """Flipkart's own category: card.vertical, or the folder in the image URL (.../xif0q/mobile-panel/...)."""
    if v.get("vertical"):
        return v["vertical"].replace("_", "-")
    for img in (v.get("media") or {}).get("images") or []:
        m = re.search(r"/image/\{@width\}/\{@height\}/[^/]+/([a-z0-9-]+)/", img.get("url", ""))
        if m:
            return m.group(1)
    return None


def _clean_url(base_url: str) -> str:
    """Keep only the product path and pid (drop search tracking params)."""
    u = urlparse(base_url)
    pid = parse_qs(u.query).get("pid", [None])[0]
    return f"{BASE}{u.path}" + (f"?pid={pid}" if pid else "")


def _price(pricing: dict | None) -> float | None:
    """What you pay: `finalPrice` when present, else the lowest price that isn't struck through (the M.R.P. is)."""
    pricing = pricing or {}
    final = (pricing.get("finalPrice") or {}).get("value")
    if final:
        return float(final)
    live = [p.get("value") for p in pricing.get("prices") or [] if not p.get("strikeOff") and p.get("value")]
    return float(min(live)) if live else None


def _colour(titles: dict, category: Category) -> str | None:
    title = titles.get("title") or ""
    if category in (Category.SNEAKERS, Category.TSHIRT):
        sub = titles.get("subtitle") or ""  # "White , 10"
        if sub:
            return sub.split(",")[0].strip() or None
        return find_colour_in_title(titles.get("newTitle") or title)
    m = re.search(r"\(([^,()]+),", title)  # "Apple iPhone 15 (Blue, 128 GB)"
    if m and not re.search(r"\d", m.group(1)):
        return m.group(1).strip()
    return None


def parse_search(state: dict, category: Category) -> list[ProductSpec]:
    out: list[ProductSpec] = []
    page = (((state or {}).get("pageDataV4") or {}).get("page") or {}).get("data") or {}
    for widgets in page.values():
        for w in widgets or []:
            for p in (((w.get("widget") or {}).get("data") or {}).get("products") or []):
                v = (p.get("productInfo") or {}).get("value")
                if not v or not v.get("baseUrl"):
                    continue
                titles = v.get("titles") or {}
                title = titles.get("title") or titles.get("newTitle") or ""
                specs_text = " | ".join(v.get("keySpecs") or [])
                avail = (v.get("availability") or {}).get("displayState")
                price = _price(v.get("pricing"))
                code_text = " ".join(filter(None, [titles.get("subtitle") if category == Category.TELEVISION else None,
                                                   re.sub(r".*Model ID:\s*", "", specs_text) if "Model ID" in specs_text else None]))
                out.append(ProductSpec(
                    title=title,
                    brand=v.get("productBrand") or titles.get("superTitle"),
                    category=category,
                    model_codes=model_codes(code_text),
                    ram_gb=parse_ram_gb(f"{title} {specs_text}") if category == Category.SMARTPHONE else None,
                    storage_gb=parse_storage_gb(f"{title} {specs_text}") if category == Category.SMARTPHONE else None,
                    screen_inches=parse_screen_inches(title) if category == Category.TELEVISION else None,
                    colour=_colour(titles, category),
                    gender=parse_gender(title) if category in (Category.SNEAKERS, Category.TSHIRT) else None,
                    product_type=garment_type(f"{title} {titles.get('newTitle') or ''}") if category == Category.TSHIRT else None,
                    kind=_kind(v),
                    url=_clean_url(v["baseUrl"]),
                    image=_image(v.get("media")),
                    price=price,
                    in_stock=(avail == "IN_STOCK") if avail else None,
                    platform_id=v.get("id"),
                ))
    return dedupe(out)


_IDENTITY_ROW = re.compile(
    r'"label_1":\{"value":\{"text":\["([^"]{2,40})"\]\}\},"label_0":\{"value":\{"text":"'
    r'(Style Code|Article Number|Model Number|Model Name|Model ID|Style Name)"')
_CODE_LABELS = ("Style Code", "Article Number")
_MODEL_LABELS = ("Model Number", "Model ID")


def identity_rows(html: str) -> list[tuple[str, str]]:
    """(label, value) for the rows of the product's own spec table that identify it."""
    return [(m.group(2), m.group(1)) for m in _IDENTITY_ROW.finditer(html)]


def listed_codes(html: str, category: Category | None = None) -> list[str]:
    """Identifier rows of the product's own spec table: Style Code / Article Number for fashion,
    Model Number / Model ID for electronics (names excluded)."""
    labels = _MODEL_LABELS if category in (Category.TELEVISION, Category.SMARTPHONE) else _CODE_LABELS
    return [v for label, v in identity_rows(html) if label in labels and re.search(r"\d", v)]


def identity_text(html: str) -> str:
    """This product's own identifiers: the spec rows that name it + the page's meta description.
    (The rest of the page also carries other products' data, e.g. "similar products".)"""
    rows = [m.group(1) for m in _IDENTITY_ROW.finditer(html)]
    desc = re.search(r'<meta name="Description" content="([^"]*)"', html)
    return " | ".join(rows + ([desc.group(1)] if desc else []))


def parse_stock_from_product_page(html: str) -> bool | None:
    m = re.search(r'"availabilityStatus"\s*:\s*"([A-Z_]+)"', html)
    if m:
        return m.group(1) == "IN_STOCK"
    m = re.search(r'schema\.org/(InStock|OutOfStock|SoldOut|PreOrder|Discontinued)', html)
    if m:
        return m.group(1) == "InStock"
    if re.search(r">\s*(Sold Out|Currently Unavailable|Coming Soon)\s*<", html, re.I):
        return False
    return None


class Flipkart(Platform):
    name = "Flipkart"
    key = "flipkart"

    def __init__(self) -> None:
        self._pages: dict[str, tuple[float, str]] = {}  # url -> (fetched_at, html); product pages are ~1.4 MB

    async def product_page(self, spec: ProductSpec) -> str | None:
        if not spec.url:
            return None
        now = time.monotonic()
        hit = self._pages.get(spec.url)
        if hit and now - hit[0] < 300:
            return hit[1]
        html = (await http.get(spec.url)).text
        if len(self._pages) > 32:
            self._pages.clear()
        self._pages[spec.url] = (now, html)
        return html

    async def search(self, query: str, category: Category) -> list[ProductSpec]:
        r = await http.get(f"{BASE}/search", params={"q": query})
        state = embedded_json(r.text, "__INITIAL_STATE__")
        if state is None:
            raise http.FetchError("Flipkart returned a page without search data")
        return parse_search(state, category)

    def identity_text(self, page: str) -> str:
        return identity_text(page)

    def listed_codes(self, page: str, category: Category | None = None) -> list[str]:
        return listed_codes(page, category)

    async def check_stock(self, spec: ProductSpec) -> bool | None:
        if spec.in_stock is not None:
            return spec.in_stock
        html = await self.product_page(spec)
        return parse_stock_from_product_page(html) if html else None
