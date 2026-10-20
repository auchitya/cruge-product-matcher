"""Croma: JSON search API + per-pincode delivery check.

The website is a client-rendered React app behind Akamai; we talk to the same
JSON endpoints the site uses (with a Chrome TLS fingerprint).

Stock: a Croma listing exists nationally but can only be *bought* where it can be
delivered. `pdp/deliveryoption?pinCode=` answers that per pincode. We ask for a few
metro pincodes and call it in stock if any of them can get it.
"""
from __future__ import annotations

import asyncio
import os
import re

from .. import http
from ..models import Category, ProductSpec
from ..normalize import model_codes, parse_ram_gb, parse_screen_inches, parse_storage_gb
from .base import Platform, dedupe

BASE = "https://www.croma.com"
API = "https://api.croma.com"
# Mumbai, Delhi, Bengaluru — override with CROMA_PINCODES=400049,110001
PINCODES = [p.strip() for p in os.getenv("CROMA_PINCODES", "400049,110001,560001").split(",") if p.strip()]


def _colour(name: str) -> str | None:
    # "SAMSUNG Galaxy S25 5G (12GB RAM, 256GB, Icyblue)" -> last item in the brackets
    m = re.search(r"\(([^()]*)\)\s*$", name)
    if not m:
        return None
    last = m.group(1).split(",")[-1].strip()
    return None if re.search(r"\d", last) else last


def parse_search(data: dict, category: Category) -> list[ProductSpec]:
    out = []
    for p in (data or {}).get("products") or []:
        name = p.get("name") or ""
        price = (p.get("price") or {}).get("value")
        out.append(ProductSpec(
            title=name,
            brand=p.get("manufacturer"),
            category=category,
            model_codes=model_codes(p.get("summary")) if category == Category.TELEVISION else [],
            ram_gb=parse_ram_gb(name) if category == Category.SMARTPHONE else None,
            storage_gb=parse_storage_gb(name) if category == Category.SMARTPHONE else None,
            screen_inches=parse_screen_inches(name) if category == Category.TELEVISION else None,
            colour=_colour(name),
            url=BASE + p["url"] if p.get("url") else None,
            image=p.get("plpImage"),
            price=float(price) if price else None,
            in_stock=None,
            platform_id=p.get("code"),
        ))
    return dedupe(out)


class Croma(Platform):
    name = "Croma"
    key = "croma"

    async def search(self, query: str, category: Category) -> list[ProductSpec]:
        r = await http.get(f"{API}/searchservices/v1/search", params={
            "currentPage": 0, "query": f"{query}:relevance", "fields": "FULL",
            "channel": "WEB", "channelCode": PINCODES[0], "spellOpt": "DEFAULT",
        })
        return parse_search(r.json(), category)

    async def check_stock(self, spec: ProductSpec) -> bool | None:
        async def one(pin: str) -> bool | None:
            try:
                r = await http.get(f"{API}/product/allchannels/v1/pdp/deliveryoption",
                                   params={"productCode": spec.platform_id, "pinCode": pin}, retries=1)
                return bool(r.json().get("stockAvailable"))
            except Exception:
                return None

        answers = await asyncio.gather(*(one(p) for p in PINCODES))
        if any(a is True for a in answers):
            return True
        if any(a is False for a in answers):
            return False
        return None
