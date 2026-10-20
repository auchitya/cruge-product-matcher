"""Amazon link in, one verdict per platform out."""
from __future__ import annotations

import asyncio
import logging
import time

from . import amazon, http
from .matcher import evaluate, source_words
from .models import Category, CandidateResult, Check, MatchResponse, PlatformResult, ProductSpec, Status
from .normalize import code_in_text, codes_match, colour_families, compact, model_codes, style_codes_match
from .platforms.base import Platform
from .platforms.croma import Croma
from .platforms.flipkart import Flipkart
from .platforms.myntra import Myntra

log = logging.getLogger(__name__)

FLIPKART, CROMA, MYNTRA = Flipkart(), Croma(), Myntra()

PLATFORMS: dict[Category, list[Platform]] = {
    Category.SMARTPHONE: [FLIPKART, CROMA],
    Category.TELEVISION: [FLIPKART, CROMA],
    Category.SNEAKERS: [FLIPKART, MYNTRA],
    Category.TSHIRT: [FLIPKART, MYNTRA],
}

STOCK_CHECKS = 3  # how many matching listings we open to look for one that is in stock
CODE_CHECKS = 10  # how many promising listings we open to compare product identifiers
CACHE_TTL = 600
_cache: dict[str, tuple[float, MatchResponse]] = {}


def build_queries(src: ProductSpec) -> list[str]:
    """Most specific search first; a looser one as a fallback."""
    brand = src.brand or ""
    words = " ".join(source_words(src))
    colour = (colour_families(src.colour) or [""])[0]
    gender = {"men": "men", "women": "women", "kids": "kids"}.get(src.gender or "", "")
    q: list[str] = []
    if src.category == Category.SMARTPHONE:
        storage = f"{src.storage_gb:g} GB" if src.storage_gb else ""
        q += [f"{brand} {words} {storage}", f"{brand} {words}"]
    elif src.category == Category.TELEVISION:
        size = f"{src.screen_inches:g} inch" if src.screen_inches else ""
        if src.model_codes:
            q.append(f"{brand} {src.model_codes[0]}")
        q += [f"{brand} {words} {size} tv"]
        if src.model_codes:
            # Platforms rename series (Amazon "FX Pro" = Flipkart "F Pro"); the model number settles it,
            # so also look at all of this brand's TVs of this size.
            q.append(f"{brand} {size} tv")
    elif src.category == Category.SNEAKERS:
        q += [f"{brand} {words} {colour} {gender} sneakers", f"{brand} {words} {gender} shoes"]
    elif src.category == Category.TSHIRT:
        kind = {"polo": "polo t-shirt", "jersey": "jersey"}.get(src.product_type or "", "t-shirt")
        q += [f"{brand} {words} {colour} {gender} {kind}", f"{brand} {colour} {gender} {kind}"]
    seen, out = set(), []
    for s in q:
        s = " ".join(s.split())
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def _rank_key(r: CandidateResult) -> tuple:
    colour_pref = next((c.ok for c in r.checks if c.name == "Colour"), False)
    return (colour_pref, r.score)


async def check_platform(platform: Platform, src: ProductSpec) -> PlatformResult:
    t0 = time.monotonic()
    result = PlatformResult(platform=platform.name, status=Status.NOT_LISTED)
    assert src.category is not None
    evaluated: list[tuple[CandidateResult, str]] = []
    seen: set[str | None] = set()  # the fallback query often returns the same listings again
    try:
        for query in build_queries(src):
            result.search_query = query
            candidates = [c for c in await platform.search(query, src.category)
                          if (c.platform_id or c.url) not in seen]
            seen.update(c.platform_id or c.url for c in candidates)
            result.candidates_seen += len(candidates)
            batch = [evaluate(src, c) for c in candidates]
            evaluated += batch
            if any(r.matched for r, _ in batch):
                break
    except Exception as e:  # network/blocking — say so instead of pretending "not listed"
        log.warning("%s search failed: %s", platform.name, e)
        result.status, result.error = Status.ERROR, f"Couldn't search {platform.name}: {e}"
        result.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return result

    # Titles are vague ("Solid Men Polo Neck Black T-Shirt") and search cards sometimes show a shortened
    # model ID. If Amazon gave an identifier (style code IH1476, model number 43NU870BPLA), open the top
    # listings and compare it with the one on the product page: that's proof either way.
    if src.category != Category.SMARTPHONE and src.model_codes:
        await _verify_identifiers(platform, src, evaluated)

    matches = sorted((x for x in evaluated if x[0].matched), key=lambda x: _rank_key(x[0]), reverse=True)
    # When some listings are proven by style code, only they are "the same product". If the proven
    # one is sold out, the answer is "out of stock", not a similar-looking shoe that happens to be in stock.
    proven = [x for x in matches if any(c.name in PROOF_CHECKS and c.ok for c in x[0].checks)]
    if proven:
        matches = proven
    misses = sorted((r for r, _ in evaluated if not r.matched), key=lambda r: r.score, reverse=True)
    seen_titles: set[str] = set()  # size variants share a title; show each once
    for r in misses:
        if r.spec.title not in seen_titles and len(result.near_misses) < 3:
            seen_titles.add(r.spec.title)
            result.near_misses.append(r)

    if not matches:
        result.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return result

    # Look at the best few matches; prefer one that can be bought right now.
    top = matches[:STOCK_CHECKS]
    stock = await asyncio.gather(*(platform.check_stock(r.spec) for r, _ in top), return_exceptions=True)
    stock = [None if isinstance(s, Exception) else s for s in stock]
    chosen_i = next((i for i, s in enumerate(stock) if s is True), None)
    if chosen_i is None:
        chosen_i = next((i for i, s in enumerate(stock) if s is False), 0)
    best, confidence = top[chosen_i]
    best.spec.in_stock = stock[chosen_i]

    result.match = best.spec
    result.checks = best.checks
    result.confidence = confidence
    if stock[chosen_i] is False:
        result.status = Status.OUT_OF_STOCK
    else:
        result.status = Status.IN_STOCK
        if stock[chosen_i] is None:
            result.notes.append("Listed, but we couldn't confirm stock.")
    colour = next((c for c in best.checks if c.name == "Colour" and not c.required), None)
    if colour and not colour.ok:
        result.notes.append(f"Only found in a different colour ({best.spec.colour}).")
    if len(matches) > 1:
        result.notes.append(f"{len(matches)} matching listings found; showing the best one.")
    result.elapsed_ms = int((time.monotonic() - t0) * 1000)
    return result


# Checks that only read titles; an exact product identifier overrides them (Flipkart calls a shirt
# "Printed" that Amazon calls "Solid" -- same style code, same shirt).
_TITLE_CHECKS = {"Model", "Pattern", "Type"}
PROOF_CHECKS = ("Style code", "Model number")


def _same_identifier(category: Category, ours: str, theirs: str) -> bool:
    if category == Category.TELEVISION:
        # strict: K-55S25B (BRAVIA 2) is not K-55S25BM2 (BRAVIA 2 II); region letters may differ
        return bool(codes_match([ours], model_codes(theirs, allow_numeric=True) or [theirs.upper()]))
    return style_codes_match(ours, theirs)  # fashion: a short size/colour suffix may differ


async def _verify_identifiers(platform: Platform, src: ProductSpec,
                              evaluated: list[tuple[CandidateResult, str]]) -> None:
    """Open the most promising listings and compare the product identifier on the page with Amazon's
    (style code for fashion, model number for TVs). Same identifier = proven same product; a different
    one = a different product, however similar the title. Mutates `evaluated` in place.

    "Promising" = passes every required check except the ones that only read titles.
    """
    assert src.category is not None
    name = "Model number" if src.category == Category.TELEVISION else "Style code"

    def overridable(c: Check) -> bool:
        # title-only checks, and a colour we simply couldn't read ("Verdigris", "Marblehead") -- but
        # never a colour we read and found different: brands reuse one code across colourways
        return c.name in _TITLE_CHECKS or (c.name == "Colour" and "can't tell" in (c.note or ""))

    def promising(r: CandidateResult) -> bool:
        return all(c.ok for c in r.checks if c.required and not overridable(c))

    def exact_colour(r: CandidateResult) -> bool:
        return compact(r.spec.colour) == compact(src.colour) if r.spec.colour and src.colour else False

    # Listings that already match by name come first: they're what we'd otherwise show, so they must be
    # checked; then the most promising of the rest.
    ranked = sorted((x for x in evaluated if promising(x[0])),
                    key=lambda x: (x[0].matched, exact_colour(x[0]), x[0].score), reverse=True)
    # pages fetched through a paid proxy cost bandwidth: open fewer
    limit = http.PROXIED_PAGE_CHECKS if ranked and http.proxy_for(ranked[0][0].spec.url or "") else CODE_CHECKS
    pool = ranked[:limit]
    pages = await asyncio.gather(*(platform.product_page(r.spec) for r, _ in pool), return_exceptions=True)
    for (r, _), page in zip(pool, pages):
        if not isinstance(page, str):
            continue
        listed = platform.listed_codes(page, src.category)
        code = next((c for c in src.model_codes if any(_same_identifier(src.category, c, x) for x in listed)), None)
        if code is None and src.category != Category.TELEVISION:
            idents = platform.identity_text(page)
            code = next((c for c in src.model_codes if code_in_text(c, idents)), None)
        if code is None:
            if listed:
                # The listing states its own identifier and it isn't Amazon's: a different product
                # ("GRAND COURT BASE 3.0" is LA1520, not IH1476)
                r.checks.append(Check(name=name, ok=False, source=src.model_codes[0], candidate=listed[0],
                                      note=f"the listing's {name.lower()} is different"))
                r.matched = False
            continue
        for c in r.checks:
            if overridable(c) and not c.ok:
                c.ok, c.note = True, f"confirmed by {name.lower()}"
        r.checks.append(Check(name=name, ok=True, required=False, source=code,
                              candidate="found on listing", note=f"exact {name.lower()} match"))
        r.score += 5
        r.matched = all(c.ok for c in r.checks if c.required)
        idx = next(j for j, x in enumerate(evaluated) if x[0] is r)
        evaluated[idx] = (r, "high")


async def match(url: str) -> MatchResponse:
    t0 = time.monotonic()
    _, asin = await amazon.resolve_url(url)
    hit = _cache.get(asin)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]

    src = await amazon.fetch_spec(url)
    if src.category is None:
        raise amazon.AmazonError(
            "This doesn't look like a smartphone, TV, pair of sneakers or t-shirt/polo/jersey — "
            "those are the four categories supported.")
    results = await asyncio.gather(*(check_platform(p, src) for p in PLATFORMS[src.category]))
    resp = MatchResponse(source=src, results=list(results), elapsed_ms=int((time.monotonic() - t0) * 1000))
    if not any(r.status == Status.ERROR for r in results):
        _cache[asin] = (time.monotonic(), resp)
    return resp
