"""Read an Amazon product page into a ProductSpec."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from selectolax.lexbor import LexborHTMLParser

from . import http
from .models import Category, ProductSpec
from .normalize import (
    colour_families, find_colour_in_title, garment_type, model_codes, norm_text, parse_gender, parse_ram_gb,
    parse_screen_inches, parse_storage_gb, title_head,
)

ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d|product|d)/([A-Z0-9]{10})(?:[/?]|$)", re.I)


class AmazonError(Exception):
    """User-facing problem with the Amazon link."""


def extract_asin(url: str) -> str | None:
    m = ASIN_RE.search(urlparse(url).path + "/")
    return m.group(1).upper() if m else None


async def resolve_url(url: str) -> tuple[str, str]:
    """Return (canonical product URL, ASIN). Follows amzn.in / amzn.to short links."""
    url = url.strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    host = urlparse(url).netloc.lower()
    if not any(h in host for h in ("amazon.", "amzn.")):
        raise AmazonError("That doesn't look like an Amazon link.")
    asin = extract_asin(url)
    if not asin:
        try:
            r = await http.get(url)
        except http.FetchError as e:
            raise AmazonError(f"Couldn't open that link ({e}).") from e
        asin = extract_asin(str(r.url))
        if not asin:
            raise AmazonError("Couldn't find a product ID (ASIN) in that link.")
    return f"https://www.amazon.in/dp/{asin}", asin


async def fetch_spec(url: str) -> ProductSpec:
    canon, asin = await resolve_url(url)
    html = ""
    for _ in range(3):
        try:
            r = await http.get(canon, retries=1)
        except http.FetchError as e:
            if "404" in str(e):
                store = urlparse(url if re.match(r"^https?://", url.strip()) else "https://" + url.strip()).netloc.lower()
                if "amazon." in store and not store.endswith("amazon.in"):
                    # The other shops are Indian, so the product is read from amazon.in; an amazon.com (or
                    # .co.uk, ...) ID often has no Indian listing
                    raise AmazonError(f"That's a link from {store.removeprefix('www.')}, and this product isn't sold "
                                      "on amazon.in. This app compares Indian stores (Flipkart, Croma, Myntra), so "
                                      "please paste the product's amazon.in link.") from e
                raise AmazonError("Amazon says this product page doesn't exist.") from e
            continue
        html = r.text
        if "productTitle" in html:
            break
    if "productTitle" not in html:
        raise AmazonError("Amazon didn't return the product page (probably a bot check). Try again in a moment.")
    spec = parse_product_page(html)
    spec.url = canon
    spec.platform_id = asin
    return spec


# ---------------------------------------------------------------- parsing


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("‎", "").replace("‏", "")).strip()


def _details(h: LexborHTMLParser) -> dict[str, str]:
    """All the key/value spec tables on the page merged into one dict (lower-cased keys)."""
    d: dict[str, str] = {}
    for tr in h.css("#productOverview_feature_div tr"):
        tds = tr.css("td")
        if len(tds) >= 2:
            d.setdefault(_clean(tds[0].text()).lower(), _clean(tds[1].text()))
    for tr in h.css("table.prodDetTable tr, #productDetails_techSpec_section_1 tr, "
                    "#productDetails_detailBullets_sections1 tr, #technicalSpecifications_section_1 tr"):
        th, td = tr.css_first("th"), tr.css_first("td")
        if th and td:
            d.setdefault(_clean(th.text()).lower(), _clean(td.text()))
    for li in h.css("#detailBullets_feature_div li, #detailBulletsWrapper_feature_div li"):
        t = _clean(li.text())
        if ":" in t:
            k, v = t.split(":", 1)
            d.setdefault(_clean(k).lower(), _clean(v))
    # fashion pages: "Product details" facts grid
    for row in h.css(".product-facts-detail"):
        cells = [_clean(c.text()) for c in row.css(".a-col-left, .a-col-right")]
        if len(cells) >= 2 and cells[0] and cells[1]:
            d.setdefault(cells[0].lower(), cells[1])
    return d


def _first(d: dict[str, str], *keys: str) -> str | None:
    for k in keys:
        v = d.get(k)
        if v and v.lower() not in ("n/a", "na", "none", "not applicable"):
            return v
    return None


# What each category looks like in Amazon's breadcrumb leaf / "Generic Name" ...
_CATEGORY_PATTERNS = [
    (Category.SMARTPHONE, r"\bsmartphones?\b|\bmobile phones?\b"),
    (Category.TELEVISION, r"\btelevisions?\b|\b(smart|led|qled|oled|4k|uhd) tvs?\b|^tvs?$"),
    (Category.SNEAKERS, r"\bsneakers?\b|\b(running|walking|sports|training|casual|basketball|skateboarding|tennis|"
                        r"athletic|outdoor) shoes?\b|\btrainers?\b"),
    (Category.TSHIRT, r"\bt ?shirts?\b|\btshirts?\b|\bpolos?\b|\bjerseys?\b|\btees?\b"),
]
# ... and words that mean "this is something else", even inside one of those departments.
_NOT_IN_SCOPE = (r"\b(covers?|cases?|chargers?|cables?|adapters?|power ?banks?|tablets?|tabs?|mounts?|stands?|brackets?|"
                 r"projectors?|soundbars?|remotes?|screen guards?|protectors?|formal|sandals?|floaters?|slippers?|"
                 r"flip ?flops?|sliders?|boots?|heels?|pumps?|loafers?|mojaris?|juttis?|vests?|innerwear|hoodies?|"
                 r"sweatshirts?|jackets?|kurtas?|shorts|track ?pants?)\b")


def _category_of(text: str) -> Category | None:
    t = norm_text(text)
    if not t or re.search(_NOT_IN_SCOPE, t):
        return None
    return next((cat for cat, pat in _CATEGORY_PATTERNS if re.search(pat, t)), None)


def detect_category(title: str, crumbs: list[str], details: dict[str, str]) -> Category | None:
    """Smartphone / TV / sneakers / t-shirt, or None when the product is anything else.

    Amazon's breadcrumb *leaf* is the most precise signal: "Smartphones", "Smart Televisions",
    "Sneakers", "Polos" -- versus "Formal Shoes", "Basic Cases", "TV Wall & Ceiling Mounts".
    Keywords elsewhere in the trail mislead ("Home Theater, TV & Video" also holds projectors;
    "T-shirts, Polos & Shirts" also holds formal shirts), so only the leaf counts.
    """
    generic = " ".join(filter(None, [details.get("generic name"), details.get("item type name")]))
    if crumbs:
        leaf = norm_text(crumbs[-1])
        if re.search(_NOT_IN_SCOPE, leaf):
            return None
        found = _category_of(leaf)
        if found:
            return found
        if any(re.search(p, leaf) for _, p in _CATEGORY_PATTERNS):
            return None
        # leaf says neither yes nor no ("Supporters' Gear > Cricket"): ask the product-type field
    if generic and re.search(_NOT_IN_SCOPE, norm_text(generic)):
        return None
    return _category_of(generic) or _category_of(_title_category_hint(title))


def _title_category_hint(title: str) -> str:
    """Last resort (no breadcrumbs, no type field): turn title keywords into a category word."""
    t = norm_text(title)
    if re.search(_NOT_IN_SCOPE, t):
        return ""
    if re.search(r"\b(smartphones?|mobile phones?|iphone|\d+\s*gb\s*ram)\b", t):
        return "smartphone"
    if re.search(r"\b(smart tv|led tv|qled|oled tv|television)\b", t):
        return "television"
    if re.search(r"\b(sneakers?|running shoes?|sports shoes?|casual shoes?)\b", t):
        return "sneakers"
    if re.search(r"\b(t ?shirts?|polo|jersey|tee)\b", t):
        return "t-shirt"
    return ""


def _brand(h: LexborHTMLParser, details: dict[str, str]) -> str | None:
    b = _first(details, "brand", "brand name")
    if b:
        return b
    logo = h.css_first("img.premium-logoByLine-brand-logo")  # premium-brand layout has a logo, not text
    if logo and logo.attributes.get("alt"):
        return logo.attributes["alt"]
    byline = h.css_first("#bylineInfo")
    if byline:
        t = _clean(byline.text())
        m = re.match(r"(?:Visit the (.+?) Store|Brand:\s*(.+))$", t)
        if m:
            return (m.group(1) or m.group(2)).strip()
    return None


def _colour(h: LexborHTMLParser, details: dict[str, str]) -> str | None:
    for sel in ("#inline-twister-expanded-dimension-text-color_name", "#variation_color_name .selection"):
        n = h.css_first(sel)
        text = _clean(n.text()) if n else ""
        if text and not re.match(r"(?i)select\b", text):  # "Select Colour" is the empty dropdown, not a colour
            return text
    return _first(details, "colour", "color", "colour name", "color name")


def _image(h: LexborHTMLParser) -> str | None:
    img = h.css_first("#landingImage") or h.css_first("#imgBlkFront")
    if img:
        return img.attributes.get("data-old-hires") or img.attributes.get("src")
    return None


def _money(text: str) -> float | None:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
    return float(m.group(0).replace(",", "")) if m else None


def _price(h: LexborHTMLParser) -> float | None:
    """The selling price ("price to pay"), never the struck-through M.R.P. or an ad's price."""
    for box in h.css("#corePriceDisplay_desktop_feature_div .priceToPay, #corePrice_feature_div .apex-pricetopay-value, "
                     "#corePriceDisplay_desktop_feature_div .apex-pricetopay-value, #corePrice_feature_div .a-price"):
        if "a-text-price" in (box.attributes.get("class") or ""):
            continue  # a-text-price = the crossed-out M.R.P.
        hidden = box.css_first(".a-offscreen")
        price = _money(hidden.text()) if hidden else None
        if price is None:  # some pages leave the hidden copy empty; read the visible digits instead
            whole, frac = box.css_first(".a-price-whole"), box.css_first(".a-price-fraction")
            if whole:
                price = _money(whole.text().rstrip(".") + ("." + frac.text() if frac else ""))
        if price:
            return price
    return None


def _in_stock(h: LexborHTMLParser) -> bool | None:
    n = h.css_first("#availability span") or h.css_first("#availability")
    if not n:
        return None
    t = _clean(n.text()).lower()
    if "unavailable" in t or "out of stock" in t:
        return False
    if "in stock" in t or "left in stock" in t:
        return True
    return None


def parse_product_page(html: str) -> ProductSpec:
    h = LexborHTMLParser(html)
    title_node = h.css_first("#productTitle")
    title = _clean(title_node.text()) if title_node else ""
    crumbs = [_clean(a.text()) for a in h.css("#wayfinding-breadcrumbs_feature_div a")]
    d = _details(h)

    category = detect_category(title, crumbs, d)
    brand = _brand(h, d) or (title.split("|")[0].split()[0] if title else None)

    ram = storage = None
    if category == Category.SMARTPHONE:
        ram_field = _first(d, "ram memory installed size", "ram memory installed", "ram", "ram size")
        ram = (parse_ram_gb(f"{ram_field} RAM") if ram_field else None) or parse_ram_gb(title)
        storage_field = _first(d, "memory storage capacity", "internal storage", "storage")
        storage = parse_storage_gb(f"{storage_field} storage") if storage_field else None
        # The title is what the seller is actually selling; it wins over a mis-filled spec table.
        storage = parse_storage_gb(title) or storage
        if storage is not None and storage < 16:
            storage = None  # no current phone ships with <16 GB; the field is mis-filled (often it's the RAM)
        if ram is not None and (ram > 32 or (storage and ram >= storage)):
            ram = None  # e.g. iPhone 16 listing with "RAM: 128 GB" (that's the storage)

    screen = parse_screen_inches(_first(d, "screen size", "screen size unit of measure", "display size class", "size")) \
        or parse_screen_inches(title)

    # Part numbers: from the spec table, plus the title for TVs (where sellers put them, e.g. "... TV 43NU870BPLA")
    codes = model_codes(" ".join(filter(None, [
        _first(d, "model number"), _first(d, "item model number"), _first(d, "style number")])), allow_numeric=True)
    if category in (Category.TELEVISION, Category.SNEAKERS, Category.TSHIRT):
        # TVs put the model number in the title ("... TV 43NU870BPLA"); shoes often the article
        # number ("adidas Samba OG ... (IG6170)") -- sometimes a different one from the spec table
        codes += [c for c in model_codes(title) if c not in codes]

    # The title is what the shopper sees; Amazon's Department field is sometimes wrong
    # ("Skechers Women Uno Night Shades" filed under Department: mens). Then the breadcrumbs.
    gender = parse_gender(title) or parse_gender(d.get("department")) or parse_gender(" ".join(crumbs))

    colour = _colour(h, d)
    if category in (Category.SNEAKERS, Category.TSHIRT) and not colour_families(colour):
        # "DUPE/CBLACK/FTWWHT" or "Sea Salt_14": use the colour the title names, if it names one
        colour = find_colour_in_title(title_head(title, cut_after_noun=True)) or find_colour_in_title(title) or colour

    return ProductSpec(
        title=title,
        brand=brand,
        category=category,
        model=_first(d, "model name", "model series"),
        model_codes=codes,
        ram_gb=ram,
        storage_gb=storage,
        screen_inches=screen if category == Category.TELEVISION else None,
        colour=colour,
        gender=gender if category in (Category.SNEAKERS, Category.TSHIRT) else None,
        product_type=garment_type(" ".join([title, d.get("shirt form type", ""), d.get("generic name", "")]))
        if category == Category.TSHIRT else None,
        image=_image(h),
        price=_price(h),
        in_stock=_in_stock(h),
    )
