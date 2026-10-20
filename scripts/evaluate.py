"""Score the matcher on the crawled corpus, offline: python scripts/evaluate.py [eval/corpus.jsonl.gz] [--show 15]

Ground truth comes from identifiers, not from hand labels:
  * fashion  -- Flipkart's Style Code / Article Number rows vs Amazon's style code
  * TVs      -- model numbers on both sides (Flipkart Model ID, Croma summary, Amazon spec table)
  * phones   -- Flipkart's Model Number row vs Amazon's item model number, where both exist
A pair whose truth isn't known is left out of the scores.

Two views:
  1. NAME RULES  -- evaluate() with identifiers hidden: how well titles alone decide "same product".
  2. SYSTEM      -- the real check_platform() decision (incl. style-code proof), replayed on the
                    recorded candidates: what a user would actually be shown.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import gzip
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import service  # noqa: E402
from app.matcher import evaluate  # noqa: E402
from app.models import Category, ProductSpec  # noqa: E402
from app.normalize import colour_families, model_codes  # noqa: E402
from app.service import _same_identifier  # noqa: E402
from app.platforms.base import Platform  # noqa: E402

CODE_LABELS = {"Style Code", "Article Number", "Model Number", "Model ID"}
DEFAULT = pathlib.Path(__file__).resolve().parent.parent / "eval" / "corpus.jsonl.gz"


def load(path) -> list[dict]:
    with gzip.open(path, "rt") as f:
        return [json.loads(line) for line in f]


FASHION_LABELS = {"Style Code", "Article Number"}
MODEL_LABELS = {"Model Number", "Model ID"}


def article_base(code: str) -> str:
    """Drop a spelled-out colour suffix: "252-8936-Navy-Blue" -> "252-8936" (the article; colour is
    compared separately). Numeric colour codes ("252-8936-17") are handled by the short-suffix rule."""
    parts = [p for p in re.split(r"[-_ /@]+", code) if p]
    while len(parts) > 1 and parts[-1].isalpha() and colour_families(parts[-1]):
        parts.pop()
    return "-".join(parts)


def truth(src: ProductSpec, cand: dict, rows: dict) -> bool | None:
    """True = same product, False = different, None = can't tell from identifiers.

    Fashion: same style code AND same main colour (some brands reuse one code across colourways).
    TVs: same model number by the strict rule (K-55S25B is not K-55S25BM2).
    Phones: None -- phone model numbers encode the colour, which the brief says doesn't matter.
    """
    cat = src.category
    if not src.model_codes or cat == Category.SMARTPHONE:
        return None
    labels = MODEL_LABELS if cat == Category.TELEVISION else FASHION_LABELS
    theirs = [v for label, v in rows.get(cand.get("platform_id"), []) if label in labels]
    if cat == Category.TELEVISION:
        theirs += list(cand.get("model_codes") or [])
    if not theirs:
        return None
    if cat != Category.TELEVISION:
        theirs = list(dict.fromkeys(theirs + [article_base(b) for b in theirs]))
    same = any(_same_identifier(cat, a, b) for a in src.model_codes for b in theirs)
    if same and cat != Category.TELEVISION:
        ours, their_colour = colour_families(src.colour), colour_families(cand.get("colour"))
        if ours and their_colour and ours[0] != their_colour[0]:
            return False  # same article number, different colourway
    return same


class Replay(Platform):
    """A platform that serves recorded candidates and product-page identifiers."""

    def __init__(self, name: str, entry: dict) -> None:
        self.name = self.key = name
        self.cands = [ProductSpec(**c) for c in entry["candidates"]]
        self.rows = entry.get("rows") or {}

    async def search(self, query, category):
        return list(self.cands)

    async def check_stock(self, spec):
        return spec.in_stock if spec.in_stock is not None else True

    async def product_page(self, spec):
        return spec.platform_id if spec.platform_id in self.rows else None

    def listed_codes(self, page, category=None):
        labels = MODEL_LABELS if category in (Category.TELEVISION, Category.SMARTPHONE) else FASHION_LABELS
        return [v for label, v in self.rows.get(page, []) if label in labels]

    def identity_text(self, page):
        return " | ".join(v for _, v in self.rows.get(page, []))


class Report:
    def __init__(self) -> None:
        self.products = 0
        self.lookups = 0
        self.names = collections.defaultdict(collections.Counter)    # category -> tp/fp/fn/tn
        self.system = collections.defaultdict(collections.Counter)   # category -> right/wrong/missed/...
        self.examples = collections.defaultdict(list)
        self.unverified: list[str] = []
        self.decisions: dict[str, str] = {}

    def total(self, key: str) -> int:
        return sum(c[key] for c in self.system.values())


def run(path=DEFAULT, show: int = 12) -> Report:
    """Replay every recorded lookup through the current rules and score it."""
    rep = Report()
    recs = [r for r in load(path) if r.get("source") and r["source"].get("category")]
    rep.products = len(recs)
    for rec in recs:
        src = ProductSpec(**rec["source"])
        # re-read codes with the current parser (the corpus stores specs parsed when it was crawled)
        fresh = model_codes(src.model, allow_numeric=True) if src.model else []
        src = src.model_copy(update={"model_codes": list(dict.fromkeys(fresh + src.model_codes))})
        cat = src.category.value
        for pname, entry in rec["platforms"].items():
            rep.lookups += 1
            if entry.get("error"):
                rep.system[cat]["platform_error"] += 1
                continue
            rows = entry.get("rows") or {}
            # 1. name rules: identifiers hidden on both sides
            blind_src = src.model_copy(update={"model_codes": []})
            any_true = False
            for c in entry["candidates"]:
                t = truth(src, c, rows)
                if t is None:
                    continue
                any_true |= t
                pred = evaluate(blind_src, ProductSpec(**{**c, "model_codes": []}))[0].matched
                key = {(True, True): "tp", (True, False): "fp", (False, True): "fn", (False, False): "tn"}[(pred, t)]
                rep.names[cat][key] += 1
                if key in ("fp", "fn") and len(rep.examples[f"name-{key}-{cat}"]) < show:
                    rep.examples[f"name-{key}-{cat}"].append(
                        f"{src.title[:60]!r} [{src.colour}]  vs  {c['title'][:60]!r} [{c.get('colour')}]")
            # 2. the real decision, replayed
            res = asyncio.run(service.check_platform(Replay(pname, entry), src))
            rep.decisions[f"{rec['asin']} {pname} | {src.title[:60]} [{src.colour}]"] = (
                f"{res.status.value}: {res.match.title[:70]} [{res.match.colour}]" if res.match else res.status.value)
            if res.match is None:
                rep.system[cat]["not_listed_but_truth_exists" if any_true else "not_listed"] += 1
                if any_true and len(rep.examples[f"sys-missed-{cat}"]) < show:
                    same = next(c for c in entry["candidates"] if truth(src, c, rows))
                    rep.examples[f"sys-missed-{cat}"].append(f"{src.title[:60]!r}  -> should be {same['title'][:60]!r}")
            else:
                t = truth(src, res.match.model_dump(mode="json"), rows)
                rep.system[cat][{True: "matched_right", False: "matched_WRONG", None: "matched_unverified"}[t]] += 1
                if t is None:
                    rep.unverified.append(f"[{cat} {pname}] {src.title[:58]!r} [{src.colour}]  ->  "
                                          f"{res.match.title[:58]!r} [{res.match.colour}]")
                if t is False and len(rep.examples[f"sys-wrong-{cat}"]) < show:
                    rep.examples[f"sys-wrong-{cat}"].append(
                        f"{src.title[:60]!r} [{src.colour}]  ->  {res.match.title[:60]!r} [{res.match.colour}]")
    return rep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", nargs="?", default=str(DEFAULT))
    ap.add_argument("--show", type=int, default=12, help="examples of each error type to print")
    ap.add_argument("--audit", type=int, default=0, help="also print N random unverifiable matches to check by eye")
    ap.add_argument("--decisions", help="write every decision to this JSON file (to diff two versions)")
    args = ap.parse_args()
    rep = run(args.corpus, args.show)

    if args.decisions:
        pathlib.Path(args.decisions).write_text(json.dumps(rep.decisions, indent=0, sort_keys=True))
    print(f"\n{rep.products} products, {rep.lookups} product x platform lookups\n")
    print("NAME RULES (identifiers hidden), on pairs whose truth is known")
    print(f"  {'category':11} {'pairs':>6} {'precision':>9} {'recall':>7}   tp/fp/fn/tn")
    for cat, c in sorted(rep.names.items()):
        n = sum(c.values())
        p = c["tp"] / max(1, c["tp"] + c["fp"])
        r = c["tp"] / max(1, c["tp"] + c["fn"])
        print(f"  {cat:11} {n:6} {p:9.1%} {r:7.1%}   {c['tp']}/{c['fp']}/{c['fn']}/{c['tn']}")
    print("\nSYSTEM (what the user sees), per product x platform")
    for cat, c in sorted(rep.system.items()):
        right, wrong = c["matched_right"], c["matched_WRONG"]
        print(f"  {cat:11} " + "  ".join(f"{k}={v}" for k, v in sorted(c.items()))
              + f"   | precision on verifiable matches: {right / max(1, right + wrong):.1%}")
    for k in sorted(rep.examples):
        print(f"\n--- {k}")
        for e in rep.examples[k]:
            print("   ", e)
    if args.audit:
        import random
        print(f"\n--- random sample of {args.audit} unverifiable matches (check by eye)")
        for e in random.Random(1).sample(rep.unverified, min(args.audit, len(rep.unverified))):
            print("   ", e)


if __name__ == "__main__":
    main()
