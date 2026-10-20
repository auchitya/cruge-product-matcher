"""Myntra: server-rendered listing/product pages with data in window.__myx."""
from __future__ import annotations

from .. import http
from ..models import Category, ProductSpec
from ..normalize import garment_type, parse_gender, tokens
from .base import Platform, dedupe, embedded_json

BASE = "https://www.myntra.com"

_GENDER = {"men": "men", "women": "women", "boys": "kids", "girls": "kids", "unisex": "unisex"}


def parse_search(myx: dict, category: Category) -> list[ProductSpec]:
    res = (((myx or {}).get("searchData") or {}).get("results") or {})
    out = []
    for p in res.get("products") or []:
        name = p.get("productName") or p.get("product") or ""
        article = ((p.get("articleType") or {}).get("typeName") or "")
        out.append(ProductSpec(
            title=f"{name}",
            brand=p.get("brand"),
            category=category,
            model=article or None,
            colour=p.get("primaryColour"),
            # the name beats the gender field when it says kids ("Nike Revolution 7 Younger Kids' Shoes")
            gender="kids" if parse_gender(name) == "kids" else _GENDER.get((p.get("gender") or "").lower()),
            kind=article or None,
            product_type=garment_type(f"{name} {article}") if category == Category.TSHIRT else None,
            url=f"{BASE}/{p['landingPageUrl']}" if p.get("landingPageUrl") else None,
            image=p.get("searchImage"),
            price=float(p["price"]) if p.get("price") else None,
            in_stock=None,
            platform_id=str(p.get("productId")),
        ))
    return dedupe(out)


def parse_stock_from_product_page(myx: dict | None) -> bool | None:
    pdp = (myx or {}).get("pdpData")
    if not pdp:
        return None
    flags = pdp.get("flags") or {}
    if flags.get("outOfStock") is True or flags.get("disableBuyButton") is True:
        return False
    sizes = pdp.get("sizes") or []
    if sizes and not any(s.get("available") for s in sizes):
        return False
    return True


class Myntra(Platform):
    name = "Myntra"
    key = "myntra"

    async def search(self, query: str, category: Category) -> list[ProductSpec]:
        slug = "-".join(tokens(query)) or "search"
        r = await http.get(f"{BASE}/{slug}", params={"rawQuery": query})
        myx = embedded_json(r.text, "__myx")
        if myx is None:
            raise http.FetchError("Myntra returned a page without search data")
        return parse_search(myx, category)

    async def check_stock(self, spec: ProductSpec) -> bool | None:
        r = await http.get(f"{BASE}/{spec.platform_id}")
        return parse_stock_from_product_page(embedded_json(r.text, "__myx"))
