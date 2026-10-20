"""Learn which title words are generic, from the crawled corpus: python scripts/learn_vocab.py [eval/corpus.jsonl.gz]

A word that many *different brands* put in their titles ("stylish", "lightweight", "oversized",
"breathable") describes a kind of product; a word only one or two brands use ("samba", "smashic",
"kayano") names a model. Counting distinct brands per word over a few thousand real titles gives
the generic words for each category without anyone typing them in.

Writes app/data/generic_words.json. Words with digits and model modifiers (pro, max, plus, ...) are
never marked generic: they're how models differ. Note that generic != meaningless: "suede" or "high"
are generic yet tell variants apart, so the matcher uses this list to decide what *counts as
evidence* of a model name, not to throw words away (see matcher._distinctive).
"""
from __future__ import annotations

import collections
import gzip
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.normalize import COLOUR_WORDS, MODIFIERS, canon_brand, tokens  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "data" / "generic_words.json"
MIN_BRANDS = 12        # used by at least this many different brands ...
MIN_SHARE = 0.02       # ... and by at least this share of the category's brands


def main(path: str) -> None:
    by_cat: dict[str, dict[str, set[str]]] = collections.defaultdict(lambda: collections.defaultdict(set))
    brands_in: dict[str, set[str]] = collections.defaultdict(set)
    titles = 0
    with gzip.open(path, "rt") as f:
        for line in f:
            rec = json.loads(line)
            src = rec.get("source") or {}
            cat = src.get("category")
            if not cat:
                continue
            listings = [src] + [c for p in rec.get("platforms", {}).values() for c in p.get("candidates", [])]
            for item in listings:
                brand = canon_brand(item.get("brand"))
                if not brand:
                    continue
                titles += 1
                brands_in[cat].add(brand)
                brand_toks = set(tokens(item.get("brand")))
                for t in set(tokens(item.get("title"))):
                    if t in brand_toks or re.search(r"\d", t) or len(t) < 3 or t in MODIFIERS:
                        continue
                    by_cat[cat][t].add(brand)

    learned = {}
    for cat, words in by_cat.items():
        need = max(MIN_BRANDS, int(MIN_SHARE * len(brands_in[cat])))
        generic = sorted(w for w, b in words.items() if len(b) >= need and w not in COLOUR_WORDS)
        learned[cat] = generic
        print(f"{cat:11} {len(brands_in[cat]):4} brands  -> {len(generic):4} generic words (used by >= {need} brands)")
    OUT.write_text(json.dumps(learned, indent=0))
    print(f"{titles} titles read -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "eval" / "corpus.jsonl.gz"))
