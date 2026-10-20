"""Turning messy product titles into comparable facts.

Every platform writes the same product differently:
    Amazon   : "Samsung Galaxy S25 5G (Icyblue, 12GB RAM, 256GB Storage) with Galaxy AI | 50MP ..."
    Flipkart : "Samsung Galaxy S25 5G (Icyblue, 256 GB)"   + keySpecs "12 GB RAM | 256 GB ROM"
    Croma    : "SAMSUNG Galaxy S25 5G (12GB RAM, 256GB, Icy Blue)"
The helpers here pull out brand, sizes, colours, model numbers and the
"identity" words of a model name so the matcher can compare like with like.
"""
from __future__ import annotations

import json
import pathlib
import re
import unicodedata

# ---------------------------------------------------------------- text basics


def norm_text(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("’", "'").replace("‘", "'").replace("‎", "").replace("‏", "")
    s = re.sub(r"(\w)'s\b", r"\1s", s)  # men's -> mens
    s = s.replace("'", " ")  # Air Force 1 '07 -> air force 1 07
    # glue numbers to their units so "138 cm" and "138cm" look the same
    s = re.sub(r"(\d)\s+(gb|tb|cms|cm|mm|mp|mah|hz|fps|inch|inches|in)\b", r"\1\2", s)
    s = re.sub(r"[^a-z0-9.+]+", " ", s)
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)  # keep decimal points only
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str | None) -> list[str]:
    return norm_text(s).split()


def compact(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", norm_text(s))


# ---------------------------------------------------------------- brands

# Groups of names that refer to the same brand.
_BRAND_GROUPS = [
    {"xiaomi", "mi", "redmi"},
    {"uspoloassn", "uspoloassociation", "uspa", "uspoloassnjeans", "uspoloassndenimco"},
    {"adidas", "adidasoriginals", "adidasperformance"},
    {"nike", "nikesportswear", "jordan", "nikejordan"},
    {"tommyhilfiger", "tommy"},
    {"lg", "lgelectronics"},
    {"tcl"},
    {"vu", "vutelevisions"},
    {"mi", "xiaomi"},
    {"jackjones", "jackandjones"},
    {"levis", "levi"},
    {"puma"},
    {"poco"},
]
_BRAND_CANON: dict[str, str] = {}
for _g in _BRAND_GROUPS:
    _canon = sorted(_g)[0]
    for _b in _g:
        _BRAND_CANON.setdefault(_b, _canon)


def canon_brand(brand: str | None) -> str:
    c = compact(brand)
    return _BRAND_CANON.get(c, c)


def brands_match(a: str | None, b: str | None) -> bool:
    ca, cb = canon_brand(a), canon_brand(b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    # "adidas originals" vs "adidas", "samsung electronics" vs "samsung"
    short, long_ = sorted((ca, cb), key=len)
    if len(short) >= 3 and long_.startswith(short):
        return True
    # initials: "VW" for "Visio World", "JJ" for "Jack & Jones"
    for x, y in ((a, b), (b, a)):
        words = [w for w in tokens(x) if w not in ("and", "the", "of")]
        if len(words) >= 2 and "".join(w[0] for w in words) == compact(y):
            return True
    return False


# ---------------------------------------------------------------- sizes

_GB = r"(\d+(?:\.\d+)?)\s*(tb|gb|mb)"


def _to_gb(num: str, unit: str) -> float:
    v = float(num)
    return v * 1024 if unit == "tb" else v / 1024 if unit == "mb" else v


def parse_ram_gb(text: str | None) -> float | None:
    t = norm_text(text)
    for pat in (rf"{_GB}\s*ram", rf"ram\s*(?:memory\s*)?(?:installed\s*)?(?:size\s*)?:?\s*{_GB}"):
        m = re.search(pat, t)
        if m:
            return _to_gb(m.group(1), m.group(2))
    return None


def parse_storage_gb(text: str | None) -> float | None:
    t = norm_text(text)
    t = re.sub(rf"expandable\s*(?:up\s*to|upto)?\s*{_GB}", " ", t)
    for pat in (rf"{_GB}\s*(?:rom|storage|internal)", rf"(?:storage|rom)\s*:?\s*{_GB}"):
        m = re.search(pat, t)
        if m:
            g = m.groups()
            num, unit = (g[0], g[1])
            return _to_gb(num, unit)
    # otherwise: the largest GB/TB figure that is not the RAM figure
    ram = parse_ram_gb(t)
    t_wo_ram = re.sub(rf"{_GB}\s*ram", " ", t)
    vals = [_to_gb(n, u) for n, u in re.findall(_GB, t_wo_ram)]
    vals = [v for v in vals if v >= 16 and v != ram]  # phones have >=16 GB storage
    return max(vals) if vals else None


def parse_screen_inches(text: str | None) -> float | None:
    t = norm_text(text)
    m = re.search(r"(\d{2,3}(?:\.\d+)?)\s*(?:inch|inches|in)\b", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d{2,3}(?:\.\d+)?)\s*cm\b", t)
    if m:
        return round(float(m.group(1)) / 2.54, 1)
    return None


def same_screen(a: float | None, b: float | None) -> bool:
    # 139 cm is listed as 55" on one site and 54.7" on another; TVs come in whole inches
    return a is not None and b is not None and abs(a - b) <= 1.0


# ---------------------------------------------------------------- colours

# shade word -> colour family. Longest keys are tried first so "navyblue" hits "navy".
_COLOUR_FAMILY = {
    "black": "black", "jet": "black", "onyx": "black", "noir": "black", "midnight": "black",
    "graphite": "grey", "charcoal": "grey", "grey": "grey", "gray": "grey", "titanium": "grey",
    "slate": "grey", "ash": "grey", "anthracite": "grey", "smoke": "grey",
    "white": "white", "ivory": "white", "offwhite": "white", "cream": "white", "pearl": "white",
    "silver": "silver", "metallic silver": "silver",
    "blue": "blue", "navy": "blue", "indigo": "blue", "teal": "blue", "turquoise": "blue",
    "aqua": "blue", "cobalt": "blue", "sky": "blue", "denim": "blue", "royal": "blue", "ocean": "blue",
    "red": "red", "maroon": "red", "burgundy": "red", "wine": "red", "crimson": "red", "cherry": "red",
    "green": "green", "olive": "green", "mint": "green", "lime": "green", "khaki": "green",
    "sage": "green", "emerald": "green", "jade": "green",
    "yellow": "yellow", "mustard": "yellow", "lemon": "yellow", "amber": "yellow",
    "pink": "pink", "rose": "pink", "peach": "pink", "coral": "pink", "fuchsia": "pink", "magenta": "pink",
    "purple": "purple", "violet": "purple", "lavender": "purple", "lilac": "purple", "mauve": "purple",
    "orange": "orange", "rust": "orange",
    "brown": "brown", "tan": "brown", "coffee": "brown", "chocolate": "brown", "camel": "brown",
    "beige": "beige", "sand": "beige", "taupe": "beige", "nude": "beige", "stone": "beige",
    "gold": "gold", "golden": "gold",
    "multi": "multi", "multicolor": "multi", "multicolour": "multi",
    # shoe-brand shade names (Nike/Puma colourways)
    "marine": "blue", "obsidian": "blue", "sail": "white", "bone": "beige", "ecru": "beige", "oatmeal": "beige",
    "phantom": "white", "fog": "grey", "orewood": "beige", "khaki": "green", "nautical": "blue",
    "oat": "beige", "gum": "brown", "ruby": "red", "salt": "white", "seasalt": "white",
    "volt": "yellow", "cyan": "blue", "mocha": "brown", "bronze": "brown", "copper": "orange",
}
# Abbreviations brands use inside colourway names ("Lt Orewood Brn", "Blk/Wht", adidas "FTWWHT",
# "PUTBEI", "LINGRN", "GRETHR"). Only tried on words we don't otherwise know, as a word's start or end.
_COLOUR_ABBR = {"blk": "black", "wht": "white", "gry": "grey", "gre": "grey", "grn": "green", "blu": "blue",
                "brn": "brown", "pnk": "pink", "pur": "purple", "yel": "yellow", "slv": "silver", "gld": "gold",
                "nvy": "blue", "nav": "blue", "bei": "beige", "org": "orange", "ora": "orange", "rd": "red",
                "red": "red", "olv": "green", "mrn": "red"}

# ~950 everyday colour names (XKCD colour survey, CC0) mapped to families from their RGB values by
# scripts/build_colours.py. Covers the long tail ("aubergine", "dusty rose", "sea green"); the
# curated list above wins where both know a word.
_DATASET_COLOURS: dict[str, str] = json.loads(
    (pathlib.Path(__file__).resolve().parent / "data" / "colours.json").read_text())
_DATASET_WORDS = {k: v for k, v in _DATASET_COLOURS.items() if " " not in k and len(k) >= 3}
_COLOUR_KEYS = sorted((k.replace(" ", "") for k in _COLOUR_FAMILY), key=len, reverse=True)
_COLOUR_FAMILY = {k.replace(" ", ""): v for k, v in _COLOUR_FAMILY.items()}
COLOUR_WORDS = set(_COLOUR_FAMILY)


# Words that describe a shade but aren't a colour themselves ("Light Marine", "Off-White", "Matte Silver").
_SHADE_MODIFIERS = {
    "light", "dark", "pale", "deep", "off", "matte", "metallic", "bright", "neon", "washed", "wash", "heather",
    "melange", "true", "core", "cool", "soft", "dusty", "vivid", "hyper", "university", "game", "summit", "pure",
    "lt", "dk", "tm", "medium", "mid", "ii", "iii",
}


_BASIC_COLOURS = {"black", "white", "grey", "gray", "blue", "red", "green", "yellow", "pink", "purple", "orange",
                  "brown", "beige", "silver", "gold"}


def _word_family(word: str) -> str | None:
    if word in _COLOUR_FAMILY:
        return _COLOUR_FAMILY[word]
    if word in _DATASET_WORDS:
        return _DATASET_WORDS[word]
    # glued names: "Icyblue", "Whitesilver", adidas "CBLACK" (4+ letters so "ash" never hides in "wash")
    hits = sorted((word.find(k), -len(k), k) for k in _COLOUR_KEYS if len(k) >= 4 and k in word)
    if hits:
        return _COLOUR_FAMILY[hits[0][2]]
    if len(word) <= 7:
        for abbr, fam in _COLOUR_ABBR.items():
            if word == abbr or (len(abbr) == 3 and (word.startswith(abbr) or word.endswith(abbr))):
                return fam
    return None


def _colour_parts(colour: str | None) -> list[tuple[str, str | None]]:
    """Split "LIGHT MARINE/BLACK-WHITE" into parts and name each part's colour family.

    In a part, the *last* colour word is the colour and earlier words describe it:
    "Midnight Navy" is navy, "Titanium Whitesilver" is white, "Jet Black" is black.
    A part like "Off" (from "Off-White") has no colour of its own and is folded into the next one.
    """
    parts: list[tuple[str, str | None]] = []
    carry = ""
    for raw in re.split(r"[/,&+()\-]| and | with ", re.sub(r"[_\d]+", " ", (colour or "").lower())):
        text = f"{carry} {raw}".strip()
        words = re.findall(r"[a-z]+", text)
        if not words:
            continue
        if all(w in _SHADE_MODIFIERS for w in words):
            carry = text
            continue
        carry = ""
        # Two basic colour names side by side are two colours ("Black Pink", "Grey Pink"), primary first;
        # otherwise earlier words describe the last one ("Midnight Navy", "Olive Green", "Jet Black").
        basics = [w for w in words if w in _BASIC_COLOURS]
        if len({_COLOUR_FAMILY[w] for w in basics}) >= 2:
            parts.extend((w, _COLOUR_FAMILY[w]) for w in basics)
            continue
        phrase = " ".join(words)
        if compact(phrase) in _COLOUR_FAMILY:
            parts.append((text, _COLOUR_FAMILY[compact(phrase)]))
            continue
        # longest known phrase ending the part: "Light Dusty Rose" -> "dusty rose"
        known = next((_DATASET_COLOURS[" ".join(words[i:])] for i in range(len(words))
                      if len(words) - i > 1 and " ".join(words[i:]) in _DATASET_COLOURS), None)
        if known:
            parts.append((text, known))
            continue
        fams = [f for f in (_word_family(w) for w in words) if f]
        parts.append((text, fams[-1] if fams else None))
    return parts


def colour_families(colour: str | None) -> list[str]:
    """Ordered colour families, primary first. An unrecognised primary colour gives []."""
    parts = _colour_parts(colour)
    if not parts or parts[0][1] is None:
        return []  # never let a secondary colour stand in for a primary we don't understand
    out: list[str] = []
    for _, fam in parts:
        if fam and fam not in out:
            out.append(fam)
    return out


def colours_match(a: str | None, b: str | None) -> tuple[bool, str]:
    if not a or not b:
        return False, "colour unknown"
    if compact(a) == compact(b):
        return True, "same colour name"
    fa, fb = colour_families(a), colour_families(b)
    if not fa or not fb:
        unknown = a if not fa else b
        return False, f"can't tell what colour '{unknown}' is"
    if fa[0] == fb[0]:
        return True, f"both {fa[0]}"
    return False, f"{fa[0]} vs {fb[0]}"


def find_colour_in_title(title: str | None) -> str | None:
    t = norm_text(title)
    for key in _COLOUR_KEYS:
        if re.search(rf"\b{re.escape(key)}\b", t):
            return key
    return None


# ---------------------------------------------------------------- model codes

_UNIT_TOKEN = re.compile(r"^\d+(\.\d+)?(gb|tb|mb|cm|cms|mm|mp|mah|hz|w|inch|inches|in|k|g|p|x|v|kg|ml|nits|fps)$")


def model_codes(text: str | None, allow_numeric: bool = False) -> list[str]:
    """Manufacturer part numbers such as UA55DUE77AKLXL, KD-55X74L, MTP03HN/A, CW2288-111.

    allow_numeric: also accept all-digit codes (Puma style numbers like 39437101). Only safe on
    spec-table fields, never on titles (where digits are prices, sizes, years).
    """
    if not text:
        return []
    raw = unicodedata.normalize("NFKC", text).upper()
    # "SNK 6291024", "GC 2577117WS": a short letter prefix + number is one code, not two
    raw = re.sub(r"\b([A-Z]{2,4})\s+(\d{5,}[A-Z]{0,3})\b", r"\1\2", raw)
    out: list[str] = []
    for m in re.finditer(r"\b[A-Z0-9]+(?:[-/][A-Z0-9]+)*\b", raw):
        code = re.sub(r"[-/]", "", m.group(0))
        if not ((5 if allow_numeric else 6) <= len(code) <= 20):
            continue
        if not re.search(r"\d", code) or (not allow_numeric and not re.search(r"[A-Z]", code)):
            continue
        if _UNIT_TOKEN.match(code.lower()) or re.match(r"^\d+X\d+$", code):
            continue
        if sum(c.isdigit() for c in code) < 2:
            continue
        if code not in out:
            out.append(code)
    return out


def codes_match(a: list[str], b: list[str]) -> str | None:
    """Return the shared model number if two lists share one.

    Exact match, or one is the other plus a *letters-only* tail. Letters at the end are
    region/colour codes (43NU870 vs 43NU870BPLA, UA55DUE77AKLXL vs UA55DUE77AKXXL); a tail
    with a digit is a new generation (K-55S25B is BRAVIA 2, K-55S25BM2 is BRAVIA 2 II).
    """
    for x in a:
        for y in b:
            if x == y:
                return x
            common = _common_prefix(x, y)
            tail_x, tail_y = x[len(common):], y[len(common):]
            if len(common) < 7 or not re.search(r"\d", common):
                continue
            if all(t.isalpha() and len(t) <= 5 for t in (tail_x, tail_y) if t):
                return common
    return None


def _common_prefix(a: str, b: str) -> str:
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[:i]


# ---------------------------------------------------------------- model words

# Adjectives sellers add to fashion titles; they never name a model ("Stylish", "for Regular wear").
_FASHION_MARKETING = {
    "stylish", "trendy", "fashion", "fashionable", "comfortable", "lightweight", "light", "weight", "premium",
    "daily", "wear", "everyday", "outdoor", "gym", "latest", "soft", "breathable", "durable", "sporty", "look",
    "office", "party", "attractive", "designer", "branded", "original", "perfect", "best", "quality", "anti",
    "skid", "slip", "resistant", "cushioned", "memory", "foam", "non", "athleisure", "smartchoice", "girls",
    "boys", "shoes", "shoe", "sneaker", "sneakers", "basketball", "skateboarding", "skate", "athletic",
    # print/pattern descriptions: every brand sells dozens of "graphic print" tees
    "graphic", "print", "prints", "typography", "striped", "stripes", "stripe", "colorblock", "colourblock",
    "colorblocked", "colourblocked", "self", "design", "embroidered", "logo", "pattern", "abstract",
}

# Words that never identify a model, by category.
_STOP_COMMON = {
    "the", "a", "an", "and", "with", "for", "of", "in", "by", "to", "on", "new", "latest", "edition",
    "pack", "official", "size", "color", "colour", "series",
}
STOPWORDS_BY_CATEGORY: dict[str, set[str]] = {
    "smartphone": _STOP_COMMON | {
        "smartphone", "smart", "phone", "mobile", "mobiles", "cellphone", "unlocked", "dual", "sim", "5g", "4g",
        "lte", "volte", "storage", "ram", "rom", "gb", "tb", "display", "camera", "battery", "processor", "ai",
        "smartchoice",
    },
    "television": _STOP_COMMON | {
        "tv", "television", "smart", "led", "qled", "oled", "uhd", "hd", "fhd", "full", "4k", "8k", "android",
        "google", "webos", "tizen", "fire", "os", "frameless", "ai", "hdr", "hdr10", "hdr10+", "dolby", "atmos",
        "speakers", "speaker", "channels", "upscaling", "cms", "cm", "inch", "inches", "smartchoice",
    },
    "sneakers": _STOP_COMMON | {
        "men", "mens", "man", "women", "womens", "woman", "ladies", "boys", "girls", "kids", "unisex", "adult",
        "shoe", "shoes", "sneaker", "sneakers", "casual", "running", "sports", "sport", "walking", "training",
        "lace", "up", "lifestyle", "footwear", "trainers", "trainer", "comfort",
    } | _FASHION_MARKETING,
    "tshirt": _STOP_COMMON | {
        "men", "mens", "man", "women", "womens", "woman", "ladies", "boys", "girls", "kids", "unisex", "adult",
        "tshirt", "tshirts", "t", "shirt", "shirts", "tee", "tees", "top", "half", "sleeve", "sleeves", "short",
        "full", "regular", "fit", "slim", "cotton", "solid", "printed", "round", "neck", "crew", "collar", "pure",
        "polyester", "fitted", "blend", "dri", "dry", "quick", "relaxed", "oversized", "brand", "v",
        "polo", "polos", "jersey", "jerseys",  # garment type is its own check
        "casual", "rich", "combed", "super", "flat", "knit", "pique", "nylon", "microfiber", "mercerised",
        "mercerized", "organic", "team", "tops", "supima", "lycra", "spandex", "stretch",
    } | _FASHION_MARKETING,
}
# Learned from data (scripts/learn_vocab.py): words that many different brands use in their titles
# for a category ("breathable", "chunky", "raglan", "suede"). They describe a kind of product, so they
# are not *evidence* of a model name -- but they can still tell variants apart, so they aren't dropped.
_LEARNED_PATH = pathlib.Path(__file__).resolve().parent / "data" / "generic_words.json"
LEARNED_GENERIC: dict[str, set[str]] = (
    {k: set(v) for k, v in json.loads(_LEARNED_PATH.read_text()).items()} if _LEARNED_PATH.exists() else {})

STOPWORDS = set().union(*STOPWORDS_BY_CATEGORY.values())

# Words that turn one model into a different model.
MODIFIERS = {
    "pro", "max", "plus", "ultra", "mini", "lite", "fe", "neo", "prime", "edge", "fold", "flip",
    "air", "nord", "note", "power", "turbo", "x", "s", "e", "r", "go", "play", "se", "core",
}


def title_head(title: str, brand: str | None = None, keep_parens: bool = False, cut_after_noun: bool = False) -> str:
    """The part of a title that names the product, before the marketing starts.

    "Samsung Galaxy S25 Ultra 5G AI Smartphone (Titanium, 12GB RAM, 256GB), 200MP Camera | ..."
        -> "Samsung Galaxy S25 Ultra 5G AI Smartphone"
    """
    parts = [p for p in re.split(r"\s*\|\s*", title) if p.strip()] or [title]
    # "Puma | Smashic Comfort Casual Sneakers": skip a leading segment that is only the brand
    t = parts[1] if len(parts) > 1 and compact(parts[0]) == compact(brand) else parts[0]
    t = re.sub(r"\bultra\s*hd\b", " ", t, flags=re.I)  # "4K Ultra HD" is not the "Ultra" model
    t = re.sub(r"\bdolby\s*vision\b", " ", t, flags=re.I)
    t = re.sub(r"\b\d\s*star\b", " ", t, flags=re.I)  # energy rating, "3 Star"
    t = re.sub(r"\b\d{3,4}\s*[x×]\s*\d{3,4}\b", " ", t)  # resolution, "3840 x 2160"
    # a short bracketed token with a digit *is* the model: "Nothing Phone (4b)", "Galaxy (2)"; keep it
    t = re.sub(r"\(\s*([A-Za-z]?\d{1,2}[A-Za-z]?)\s*\)", r" \1 ", t)
    if not keep_parens:
        t = re.split(r"[(,]", t)[0] or t
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.split(r"\s+with\s+|:\s", t)[0]
    # "Apple iPhone 15 (128 GB) - Black": a dash before a short colour/pack tail ends the name;
    # elsewhere it's part of it ("Skechers SUMMITS - BRISBANE")
    dash = re.search(r"\s+[-–]\s+", t)
    if dash:
        tail = t[dash.end():]
        short_attribute = len(tail.split()) <= 3 and (find_colour_in_title(tail) or re.search(r"(?i)pack|set|size", tail))
        t = t[:dash.start()] if short_attribute else re.sub(r"\s+[-–]\s+", " ", t)
    t = re.sub(r"\b\d+\s*%", " ", t)  # "100% Cotton"
    t = re.sub(r"(?i)\b(uk|us|eu|size)\s*-?\s*\d+(\.\d)?\b|\b\d+(\.\d)?\s*(uk|us|eu)\b", " ", t)  # shoe sizes
    # Amazon fashion titles carry colour and size after the product noun:
    # "adidas Samba OG Sneaker Oat/Wonder White/Gum 10 UK" -> "adidas Samba OG Sneaker".
    # (Not for platform titles: Myntra's "...Tshirt-2714" keeps its model number at the end.)
    m = cut_after_noun and re.search(r"(?i)\S\s+(sneakers?|shoes?|trainers?|t-?\s?shirts?|tees?|jerseys?|polo shirts?)\b", t)
    if m:
        t = t[:m.end()]
    return t


def model_words(title: str, brand: str | None, category: str | None = None, keep_parens: bool = False,
                drop_brand_aliases: bool = True, cut_after_noun: bool = False) -> list[str]:
    """Title words that describe *which model* this is (not sizes, colours, marketing)."""
    toks = tokens(title_head(title, brand, keep_parens, cut_after_noun))
    stop = STOPWORDS_BY_CATEGORY.get(category or "", STOPWORDS)
    brand_toks = set(tokens(brand)) | {compact(brand)}
    out = []
    for tok in toks:
        if tok in brand_toks or tok in stop or tok in COLOUR_WORDS:
            continue
        if drop_brand_aliases and brand and len(tok) >= 3 and brands_match(tok, brand):
            continue  # another name for the same brand: "Jordan Nike Sneakers"
        if _UNIT_TOKEN.match(tok) or re.fullmatch(r"(19|20)\d\d", tok) or re.fullmatch(r"ip\d\d", tok):
            continue
        if len(tok) == 1 and tok not in MODIFIERS and not tok.isdigit():
            continue
        if re.fullmatch(r"[a-z0-9]{6,}", tok) and re.search(r"\d", tok) and re.search(r"[a-z]", tok) \
                and sum(c.isdigit() for c in tok) >= 2:
            continue  # part number — compared separately
        if tok not in out:
            out.append(tok)
    return out


def identity_words(words: list[str]) -> set[str]:
    """The words that *must* agree: numbers (15, s25, 13r, 90) and modifiers (pro, max, ultra)."""
    return {w for w in words if re.search(r"\d", w) or w in MODIFIERS}


_SYNONYMS = {"indian": "india", "lo": "low", "hi": "high", "wmns": "women", "tshirt": "tee"}


def stem(w: str) -> str:
    """Tiny stemmer so "tipped" and "tipping" agree (and "Indian" and "India")."""
    w = _SYNONYMS.get(w, w)
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def dice(a: list[str], b: list[str]) -> float:
    """Similarity of two word lists (0..1): shared words counted against both sides."""
    sa, sb = {stem(w) for w in a}, {stem(w) for w in b}
    if not sa or not sb:
        return 0.0
    return 2 * len(sa & sb) / (len(sa) + len(sb))


def extra_words(source: list[str], candidate: list[str]) -> list[str]:
    """Distinctive candidate words the source doesn't have ("Jordan Flight" in "Jordan Flight Club Tee")."""
    have = {stem(w) for w in source}
    return [w for w in candidate if len(w) >= 3 and stem(w) not in have]


def seasons(text: str | None) -> set[str]:
    """Kit seasons / years in a title: "2025/2026", "25/26", "IPL 2026" -> {"25-26"} / {"26"}."""
    t = (text or "").lower()
    out = {f"{a[-2:]}-{b[-2:]}" for a, b in re.findall(r"\b((?:20)?\d\d)\s*[/-]\s*((?:20)?\d\d)\b", t)
           if int(b[-2:]) == int(a[-2:]) + 1}
    if not out:
        out = {y[-2:] for y in re.findall(r"\b(20[1-3]\d)\b", t)}
    return out


def missing_words(source: list[str], candidate: list[str]) -> list[str]:
    """Distinctive (3+ letter) source words that the candidate doesn't mention."""
    have = {stem(w) for w in candidate}
    return [w for w in source if len(w) >= 3 and stem(w) not in have]


def allowed_missing(n: int) -> int:
    """How many distinctive words a candidate may leave out: none of 1-3, one of 4-6, two beyond.
    ("Court Vision Lo Suede" without "suede" is a different shoe.)"""
    return 0 if n <= 3 else 1 if n <= 6 else 2


def overlap(a: list[str], b: list[str]) -> float:
    """Share of the shorter word list that appears in the longer one (0..1)."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


# ---------------------------------------------------------------- fashion bits


def parse_gender(text: str | None) -> str | None:
    t = f" {norm_text(text)} "
    kid = re.search(r"\b(boys?|girls?|kids?|child|children|infants?|toddlers?|baby|junior|gs|ps|td|youth|"
                    r"older kids|younger kids|unisex child)\b", t)
    women = re.search(r"\b(women|womens|woman|ladies|female|wmns)\b", t)
    men = re.search(r"\b(men|mens|man|male)\b", t)
    if kid and not (men or women):
        return "kids"  # "Nike Unisex Kids Court Borough (GS)" is a kids' shoe, not an adult unisex one
    if re.search(r"\bunisex\b", t):
        return "unisex"
    if women and not men:
        return "women"
    if men and not women:
        return "men"
    if men and women:
        return "unisex"
    return None


def genders_compatible(a: str | None, b: str | None) -> bool:
    if not a or not b or a == b:
        return True
    return "unisex" in (a, b) and "kids" not in (a, b)


def garment_type(text: str | None) -> str | None:
    """'polo', 'jersey', 'tshirt', or 'tshirt/v-neck' / 'tshirt/round-neck' when the neck is stated."""
    t = norm_text(text)
    t_wo_brand = re.sub(r"\bu ?s polo assn\b|\bus polo\b|\bpolo assn\b|\bpolo ralph\b", " ", t)
    if re.search(r"\b(vests?|innerwear|undershirts?|briefs?|trunks?)\b", t):
        return None  # innerwear isn't a t-shirt
    t = re.sub(r"\b(cotton|single|knit|knitted) jersey\b|\bjersey (knit|fabric|cotton)\b", " ", t)  # the fabric
    if "jersey" in t:
        base = "jersey"
    elif re.search(r"\bpolo\b", t_wo_brand):
        return "polo"
    elif re.search(r"\bt ?shirts?\b|\btees?\b|tshirt", t):
        base = "tshirt"
    else:
        return None
    if re.search(r"\bv ?neck\b|\bvneck\b", t):
        return f"{base}/v-neck"
    if re.search(r"\b(round|crew) ?neck\b|\bcrew\b", t):
        return f"{base}/round-neck"
    if re.search(r"\bhenley\b", t):
        return f"{base}/henley"
    if re.search(r"\bhood(ed|ie)?\b", t):
        return f"{base}/hooded"
    return base


def garment_types_compatible(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return True
    base_a, _, neck_a = a.partition("/")
    base_b, _, neck_b = b.partition("/")
    if (base_a == "polo") != (base_b == "polo"):
        return False  # a polo is never the same product as a t-shirt
    # jersey vs t-shirt is fine: sellers label the same item either way
    return not (neck_a and neck_b and neck_a != neck_b)


def style_codes_match(a: str, b: str) -> bool:
    """Same article, allowing a short size/colour suffix one side adds:
    IO0461 = IO0461-100, BBMH9007U = BBMH9007U06, 394371-01 = 39437101 -- but FX5501 != FX5502."""
    a, b = re.sub(r"[^A-Z0-9]", "", a.upper()), re.sub(r"[^A-Z0-9]", "", b.upper())
    if not a or not b:
        return False
    short, long_ = sorted((a, b), key=len)
    return long_.startswith(short) and len(short) >= 5 and len(long_) - len(short) <= 3


def code_in_text(code: str, text: str) -> bool:
    """Is a style code like 39437101 present in a page, allowing 394371-01 / 394371_01 spellings?"""
    if len(code) < 5:
        return False
    pat = r"(?<![A-Z0-9])" + r"[-_ /]?".join(map(re.escape, code)) + r"(?![A-Z0-9])"
    return re.search(pat, text.upper()) is not None


# The platform's own category label must fit what we're looking for (Flipkart: "mobile" yes, "mobile-panel" no).
_KIND_OK = {
    "smartphone": lambda k: k in ("mobile", "mobiles"),
    "television": lambda k: k in ("television", "televisions", "tv"),
    "sneakers": lambda k: ("shoe" in k or "sneaker" in k)
    and not re.search(r"lace|care|rack|polish|bag|insole|clean|cover|formal|sandal|flip|slipper|boot|heel", k),
    "tshirt": lambda k: bool(re.search(r"t-shirt|tshirt|jersey|polo", k)),
}


def kind_fits(category: str, kind: str | None) -> bool:
    if not kind:
        return True
    check = _KIND_OK.get(category)
    return check(kind.lower()) if check else True


_ACCESSORY = re.compile(
    r"\b(back panel|panel|cover|case|tempered glass|screen guard|screen protector|protector|charger|adapter|cable|"
    r"wall mount|bracket|power bank|earphones?|earbuds|headphones?|shoe ?laces?|insoles?|socks?|cleaner)\b")


# What the product itself is called, per category: a title naming it is the product, not an accessory
_PRODUCT_NOUN = {
    "smartphone": r"\b(smart ?phones?|mobiles?|5g phone)\b",
    "television": r"\b(tv|television|smart tv|led tv)\b",
    "sneakers": r"\b(sneakers?|shoes?|trainers?)\b",
    "tshirt": r"\b(t ?shirts?|tees?|polos?|jerseys?)\b",
}


def is_accessory(title: str | None, category: str | None = None) -> bool:
    """Accessory listings ride on the product's name ("Back Panel for Galaxy M30", "Laces for Sneakers").

    A title that names the product itself isn't one, even when it lists features that sound like
    accessories ("CAMPUS Casual Shoes for Women | Extra-Cushioned Memory Foam Insole").
    """
    t = norm_text(title)
    head = re.split(r"\s+with\s+|\(", t.replace(" for ", " with "), maxsplit=1)[0]
    noun = _PRODUCT_NOUN.get(category or "")
    if noun:
        first = re.split(r"\s*\|\s*", title or "")[0]  # features start after the first "|"
        before_for = norm_text(re.split(r"(?i)\s(?:for|compatible with)\s", first, maxsplit=1)[0])
        if re.search(noun, before_for) and not _ACCESSORY.search(before_for):
            return False  # names the product (and no accessory) before any "for ...": it is the product
    return bool(_ACCESSORY.search(head)) or bool(re.search(r"\b(compatible|for)\b", t) and _ACCESSORY.search(t))


_NOT_SNEAKERS = re.compile(r"\b(formal|derby|derbys|oxford|brogue|loafers?|moccasins?|sandals?|floaters?|sliders?|"
                           r"flip ?flops?|slippers?|boots?|heels?|pumps?|mojaris?|juttis?|clogs?)\b")


def is_other_footwear(title: str | None) -> bool:
    """Flipkart files all footwear under "shoe"; the title says if it's a formal shoe, sandal or boot."""
    return bool(_NOT_SNEAKERS.search(norm_text(title)))


def garment_pattern(text: str | None) -> str | None:
    """solid / striped / checked / colourblock / printed, if the title says."""
    t = norm_text(text)
    for name, pat in (("striped", r"\bstrip(e|ed|es)\b"), ("checked", r"\bcheck(s|ed)?\b"),
                      ("colourblock", r"\bcolou?r ?block(ed)?\b"),
                      ("printed", r"\b(printed|print|graphic|typography|abstract)\b"), ("solid", r"\bsolid\b")):
        if re.search(pat, t):
            return name
    return None


def is_refurbished(text: str | None) -> bool:
    return bool(re.search(r"\b(renewed|refurbished|pre owned|preowned|used|open box)\b", norm_text(text)))
