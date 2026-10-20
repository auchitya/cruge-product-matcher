"""Myntra: server-rendered listing/product pages with data in window.__myx.

From some networks (cloud servers) the web pages come back without that data, so the adapter falls
back to the JSON API the Myntra web app itself calls (/gateway/v2/...), which returns the same
objects.
"""
from __future__ import annotations

import asyncio

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
    # web page: {"pdpData": {...}}; JSON API: {"style": {...}} -- same fields
    pdp = (myx or {}).get("pdpData") or (myx or {}).get("style")
    if not pdp:
        return None
    flags = pdp.get("flags") or {}
    if flags.get("outOfStock") is True or flags.get("disableBuyButton") is True:
        return False
    sizes = pdp.get("sizes") or []
    if sizes and not any(s.get("available") for s in sizes):
        return False
    return True


_API_HEADERS = {"x-meta-app": "channel=web", "x-myntraweb": "Yes", "x-requested-with": "browser",
                "Accept": "application/json"}


_cookies_ready = False
_cookie_lock = asyncio.Lock()


async def warm_cookies(refresh: bool = False) -> None:
    """Fetch the homepage once for the session cookies the JSON API needs (401 without them).
    Done at server start, so the first lookup doesn't pay for a refused call plus the homepage."""
    global _cookies_ready
    async with _cookie_lock:
        if refresh or not _cookies_ready:
            await http.get(f"{BASE}/", retries=1)
            _cookies_ready = True


async def _api_get(url: str, **params) -> dict:
    """GET a Myntra JSON API with the homepage's session cookies, refreshing them once if refused."""
    if not _cookies_ready:
        try:
            await warm_cookies()
        except http.FetchError:
            pass  # try the API anyway
    try:
        r = await http.get(url, headers=_API_HEADERS, params=params or None, retries=1)
    except http.FetchError as e:
        if "401" not in str(e) and "403" not in str(e):
            raise
        await warm_cookies(refresh=True)  # cookies expired: pick up new ones, then try once more
        r = await http.get(url, headers=_API_HEADERS, params=params or None, retries=1)
    try:
        return r.json()
    except ValueError as e:
        raise http.FetchError("Myntra's API returned something that isn't JSON") from e


class Myntra(Platform):
    name = "Myntra"
    key = "myntra"

    async def search(self, query: str, category: Category) -> list[ProductSpec]:
        slug = "-".join(tokens(query)) or "search"
        myx = None
        if not http.proxy_for(BASE):  # through a paid proxy, skip the ~500 KB page and use the ~60 KB API
            r = await http.get(f"{BASE}/{slug}", params={"rawQuery": query})
            myx = embedded_json(r.text, "__myx")
        if myx is None:  # page without data (seen from cloud servers): ask the JSON API instead
            results = await _api_get(f"{BASE}/gateway/v2/search/{slug}", rawQuery=query, rows=50, o=0,
                                     plaEnabled="false")
            myx = {"searchData": {"results": results}}
        return parse_search(myx, category)

    async def check_stock(self, spec: ProductSpec) -> bool | None:
        myx = None
        if not http.proxy_for(BASE):
            r = await http.get(f"{BASE}/{spec.platform_id}")
            myx = embedded_json(r.text, "__myx")
        if myx is None:
            try:
                myx = await _api_get(f"{BASE}/gateway/v2/product/{spec.platform_id}")
            except http.FetchError:
                return None
        return parse_stock_from_product_page(myx)
