"""Decide whether a candidate listing is the same product as the Amazon one.

Every decision is a list of named checks. A candidate matches only when every
*required* check passes; optional checks (like phone colour) only change ranking.

    category      | required on top of brand + model
    --------------|---------------------------------
    smartphone    | RAM and storage
    television    | screen size
    sneakers      | colour (+ gender must not clash)
    t-shirts etc. | colour (+ gender, and polo vs t-shirt must not clash)
"""
from __future__ import annotations

import re

from .models import CandidateResult, Category, Check, ProductSpec
from .normalize import (
    LEARNED_GENERIC, allowed_missing, brands_match, codes_match, colours_match, compact, dice, extra_words,
    garment_pattern, garment_types_compatible, genders_compatible, identity_words, is_accessory, is_other_footwear,
    is_refurbished, kind_fits, missing_words, model_codes, model_words, overlap, same_screen, seasons, tokens,
)

FASHION = (Category.SNEAKERS, Category.TSHIRT)


def _fmt_gb(v: float | None) -> str | None:
    if v is None:
        return None
    return f"{v / 1024:g} TB" if v >= 1024 else f"{v:g} GB"


def source_words(src: ProductSpec) -> list[str]:
    cat = src.category.value if src.category else None
    words = model_words(src.title, src.brand, cat, keep_parens=src.category == Category.TELEVISION,
                        cut_after_noun=src.category in FASHION)
    # Amazon's "Model Name" field is clean for shoes ("Smashic", "Grand Court 3.0") -- unless it's really
    # a part number ("Rsl1448a-10"), whose leftover "10" would match any shoe.
    if src.category == Category.SNEAKERS and src.model and "_" not in src.model and len(src.model) < 40 \
            and not model_codes(src.model, allow_numeric=True):
        for w in model_words(src.model, src.brand, cat):
            if w not in words:
                words.append(w)
    # TVs: a short series code in "Model Name" (TCL "T8D") is the model
    if src.category == Category.TELEVISION and src.model and re.fullmatch(r"[A-Za-z0-9]{2,8}", src.model) \
            and re.search(r"\d", src.model) and src.model.lower() not in words:
        words.append(src.model.lower())
    return words


def _distinctive(words: list[str], category: Category | None = None) -> list[str]:
    """Words that can name a fashion model: 3+ characters, and not a word many brands use for this
    category (learned from data: "breathable", "chunky", "suede" describe, they don't name).
    Numbers count from 3 digits (New Balance "574" is a model; a stray "10" from a part number isn't)."""
    generic = LEARNED_GENERIC.get(category.value, set()) if category else set()
    return [w for w in words if len(w) >= 3 and (w not in generic or re.search(r"\d", w))]


def _brand_check(src: ProductSpec, cand: ProductSpec) -> Check:
    if not src.brand:
        # Amazon page without a brand field: trust the title's first word
        first = tokens(src.title)[:1]
        ok = bool(first) and compact(first[0]) == compact(cand.brand or (tokens(cand.title)[:1] or [""])[0])
        return Check(name="Brand", ok=ok, source=f"{first[0] if first else '?'} (from title)", candidate=cand.brand or "—")
    ok = brands_match(src.brand, cand.brand)
    if not ok and not cand.brand and src.brand:
        # Some listings only carry the brand inside the title
        ok = compact(src.brand) in compact(" ".join(tokens(cand.title)[:4]))
    return Check(name="Brand", ok=ok, source=src.brand, candidate=cand.brand or "—")


def _model_check(src: ProductSpec, cand: ProductSpec) -> tuple[Check, float, str]:
    """Returns (check, score 0..3, confidence)."""
    cat = src.category
    shared = codes_match(src.model_codes, cand.model_codes)
    if shared:
        return Check(name="Model", ok=True, source=src.model_codes[0], candidate=cand.model_codes[0],
                     note=f"same model number ({shared})"), 3.0, "high"
    if cat == Category.TELEVISION and src.model_codes and cand.model_codes:
        return Check(name="Model", ok=False, source=src.model_codes[0], candidate=cand.model_codes[0],
                     note="different model number"), 0.0, "low"

    sw = source_words(src)
    # On the listing, a sibling brand is a different line ("Nike *Jordan* Flight Club"), so keep it
    cw = model_words(cand.title, cand.brand or src.brand, cat.value if cat else None,
                     keep_parens=cat == Category.TELEVISION, drop_brand_aliases=False)
    # Either side's brand words ("Arrow Sport" on Flipkart) and the listing's own colour words
    # ("Samba OG Oat/Gum") aren't model words.
    brand_words = set(tokens(src.brand)) | set(tokens(cand.brand))
    sw = [w for w in sw if w not in brand_words and (cat not in FASHION or w not in set(tokens(src.colour)))]
    cw = [w for w in cw if w not in brand_words and (cat not in FASHION or w not in set(tokens(cand.colour)))]
    si, ci = identity_words(sw), identity_words(cw)
    ov = overlap(sw, cw)
    shown_s, shown_c = " ".join(sw) or "—", " ".join(cw) or "—"

    if cat in FASHION:
        if si and ci and si != ci:
            return Check(name="Model", ok=False, source=shown_s, candidate=shown_c,
                         note=f"different model ({' '.join(sorted(si))} vs {' '.join(sorted(ci))})"), 0.0, "low"
        distinctive = _distinctive(sw, cat)
        sim = dice(sw, cw)
        extra = extra_words(sw, _distinctive(cw, cat))
        miss = missing_words(sw, cw)  # every source word counts here -- generic ones too ("suede")
        # A name made only of generic words still identifies a model when the whole phrase is there
        # and nothing else is: "Converse Sport Casual Low Top" <-> "Sport Casual Low Top Sneakers".
        # ("High Top" alone is a shoe shape, not a name: two words need one that isn't generic -- "Classic
        # CT S", "OG-22" -- or three words -- "Sport Casual Low Top")
        generic = LEARNED_GENERIC.get(cat.value, set())
        named = [w for w in sw if len(w) >= 2]
        whole_phrase = not miss and not extra and (
            len(named) >= 3 or (len(named) >= 2 and any(w not in generic for w in named)))
        if not distinctive and not whole_phrase:
            # e.g. "adidas Men Polyester Fitted T-Shirt": nothing to compare, only a style code can confirm
            return Check(name="Model", ok=False, source="(no model name on Amazon)" if not sw else shown_s,
                         candidate=shown_c, note="Amazon gives no model name; needs a style-code match"), 0.0, "low"
        # The model's number must be there ("Wonder-13" is not "Wonder") -- numbers from the title only:
        # Amazon's Model Name field pads names ("Modern Cool 1")
        title_numbers = {w for w in model_words(src.title, src.brand, cat.value, cut_after_noun=True)
                         if re.search(r"\d", w)}
        if title_numbers - ci:
            return Check(name="Model", ok=False, source=shown_s, candidate=shown_c,
                         note=f"missing model number {' '.join(sorted(title_numbers - ci))}"), sim, "low"
        if len(extra) > max(1, len(distinctive)):
            # "Club Tee" vs "Jordan Flight Club Tee": the candidate is mostly a different name
            return Check(name="Model", ok=False, source=shown_s, candidate=shown_c,
                         note=f"a different line ({' '.join(extra)})"), sim, "low"
        if len(miss) <= allowed_missing(len(distinctive)) and (cw or not distinctive):
            conf = "high" if not miss and len(distinctive) >= 2 else "medium"
            return Check(name="Model", ok=True, source=shown_s, candidate=shown_c,
                         note="same model name" if not miss else f"same model name (no '{' '.join(miss)}')"), \
                1.0 + 2 * sim, conf
        return Check(name="Model", ok=False, source=shown_s, candidate=shown_c,
                     note=f"missing '{' '.join(miss)}'" if miss else "different model name"), sim, "low"

    # Electronics: the numbers and modifiers (15 / s25 / ultra / pro / plus) must agree exactly.
    if si != ci:
        missing = sorted(si - ci)
        extra = sorted(ci - si)
        bits = ([f"missing {' '.join(missing)}"] if missing else []) + ([f"extra {' '.join(extra)}"] if extra else [])
        return Check(name="Model", ok=False, source=shown_s, candidate=shown_c,
                     note="different model: " + ", ".join(bits)), 0.0, "low"
    if not si and ov < 0.5:
        return Check(name="Model", ok=False, source=shown_s, candidate=shown_c,
                     note="model names don't line up"), ov, "low"
    # The product-line words (galaxy, iphone, bravia, fx) must also line up: "FX Pro" is not "X Pro".
    rest_s, rest_c = [w for w in sw if w not in si], [w for w in cw if w not in ci]
    if rest_s and overlap(rest_s, rest_c) == 0:
        return Check(name="Model", ok=False, source=shown_s, candidate=shown_c,
                     note=f"different product line ({' '.join(rest_s)} vs {' '.join(rest_c) or 'nothing'})"), 0.5, "low"
    return Check(name="Model", ok=True, source=shown_s, candidate=shown_c,
                 note="same model name"), 2.0 + ov, "high" if si else "medium"


def evaluate(src: ProductSpec, cand: ProductSpec) -> tuple[CandidateResult, str]:
    """Compare one candidate to the source. Returns (result, confidence)."""
    checks: list[Check] = []
    score = 0.0

    brand = _brand_check(src, cand)
    checks.append(brand)
    score += 1.0 if brand.ok else 0

    if is_refurbished(cand.title):
        checks.append(Check(name="Condition", ok=False, candidate="refurbished/used", note="not a new unit"))
    if src.category and not kind_fits(src.category.value, cand.kind):
        checks.append(Check(name="Category", ok=False, source=src.category.value, candidate=cand.kind,
                            note="the platform files this listing under a different category"))
    elif src.category == Category.SNEAKERS and is_other_footwear(cand.title):
        checks.append(Check(name="Category", ok=False, source="sneakers", candidate=cand.title[:40],
                            note="a formal shoe, sandal or boot, not a sneaker"))
    elif is_accessory(cand.title, src.category.value if src.category else None):
        checks.append(Check(name="Category", ok=False, source=src.category.value if src.category else None,
                            candidate="accessory", note="an accessory for the product, not the product"))

    model, model_score, confidence = _model_check(src, cand)
    checks.append(model)
    score += model_score

    cat = src.category
    if cat == Category.SMARTPHONE:
        if src.ram_gb is None and cand.ram_gb is None:
            checks.append(Check(name="RAM", ok=True, note="not listed on either (normal for iPhones)"))
        elif src.ram_gb is not None and cand.ram_gb is None:
            checks.append(Check(name="RAM", ok=True, source=_fmt_gb(src.ram_gb), candidate="not listed",
                                note="not stated on this listing"))
            score += 0.2
        else:
            ok = src.ram_gb == cand.ram_gb
            checks.append(Check(name="RAM", ok=ok, source=_fmt_gb(src.ram_gb), candidate=_fmt_gb(cand.ram_gb)))
            score += 1.0 if ok else 0
        ok = src.storage_gb is not None and src.storage_gb == cand.storage_gb
        checks.append(Check(name="Storage", ok=ok, source=_fmt_gb(src.storage_gb),
                            candidate=_fmt_gb(cand.storage_gb) or "not listed"))
        score += 1.0 if ok else 0

    if cat == Category.TELEVISION:
        ok = same_screen(src.screen_inches, cand.screen_inches)
        checks.append(Check(name="Screen size",
                            ok=ok,
                            source=f"{src.screen_inches:g}\"" if src.screen_inches else None,
                            candidate=f"{cand.screen_inches:g}\"" if cand.screen_inches else "not listed"))
        score += 1.0 if ok else 0

    if cat in FASHION:
        ok, why = colours_match(src.colour, cand.colour)
        checks.append(Check(name="Colour", ok=ok, source=src.colour, candidate=cand.colour or "not listed", note=why))
        score += 1.0 if ok else 0
        g_ok = genders_compatible(src.gender, cand.gender)
        checks.append(Check(name="Gender", ok=g_ok, source=src.gender or "—", candidate=cand.gender or "—"))
        if cat == Category.TSHIRT and src.product_type and cand.product_type:
            t_ok = garment_types_compatible(src.product_type, cand.product_type)
            checks.append(Check(name="Type", ok=t_ok, source=src.product_type, candidate=cand.product_type))
            score += 0.5 if t_ok else 0
        if cat == Category.TSHIRT:
            ss, cs = seasons(src.title), seasons(cand.title)
            same_kind = all("-" in x for x in ss | cs) or not any("-" in x for x in ss | cs)
            if ss and cs and same_kind:
                checks.append(Check(name="Season", ok=bool(ss & cs), source=" ".join(sorted(ss)),
                                    candidate=" ".join(sorted(cs)),
                                    note=None if ss & cs else "a different season's kit"))
            sp, cp = garment_pattern(src.title), garment_pattern(cand.title)
            if sp and cp:
                checks.append(Check(name="Pattern", ok=sp == cp, source=sp, candidate=cp,
                                    note=None if sp == cp else "a solid shirt is not a striped or printed one"))
    else:
        # Colour is not part of "same product" for phones/TVs, but prefer the same colour when there is a choice.
        if src.colour and cand.colour:
            ok, why = colours_match(src.colour, cand.colour)
            checks.append(Check(name="Colour", ok=ok, required=False, source=src.colour, candidate=cand.colour,
                                note=why if ok else "different colour (allowed for this category)"))
            score += 0.3 if ok else 0

    matched = all(c.ok for c in checks if c.required)
    return CandidateResult(spec=cand, matched=matched, score=round(score, 3), checks=checks), confidence
