from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from ..models import Category, ProductSpec


class Platform(ABC):
    name: str
    key: str

    @abstractmethod
    async def search(self, query: str, category: Category) -> list[ProductSpec]:
        """Return candidate products for a search query (best effort, may be empty)."""

    async def check_stock(self, spec: ProductSpec) -> bool | None:
        """Can the candidate be bought right now? None = unknown."""
        return spec.in_stock

    async def product_page(self, spec: ProductSpec) -> str | None:
        """Raw product page, for platforms whose pages carry extra proof (e.g. a style code)."""
        return None

    def listed_codes(self, page: str, category: Category | None = None) -> list[str]:
        """Identifiers the product page states in labelled fields: style code for fashion, model
        number for electronics (empty if the platform doesn't show any)."""
        return []

    def identity_text(self, page: str) -> str:
        """The part of a product page that describes *this* product (not recommendations).
        Style codes are only looked for here."""
        return page


def embedded_json(html: str, var: str) -> dict | None:
    """Pull `window.<var> = {...}` out of a server-rendered page."""
    m = re.search(rf"window\.{re.escape(var)}\s*=\s*(\{{.*?\}})\s*;?\s*</script>", html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def dedupe(specs: list[ProductSpec]) -> list[ProductSpec]:
    seen: set[str] = set()
    out = []
    for s in specs:
        key = s.platform_id or s.url or s.title
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out
