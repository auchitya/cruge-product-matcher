"""Crawl a large evaluation corpus (live): python scripts/build_corpus.py [--per-query 3] [--out eval/corpus.jsonl.gz]

For each Amazon product found by a set of brand x category searches, record:
  * the parsed Amazon spec
  * every candidate each platform returns for the app's own search queries
  * for Flipkart, the identity rows (Style Code / Article Number / Model Number / Model ID) of the
    product pages of same-brand candidates -- the ground truth used by scripts/evaluate.py

Nothing here is used at runtime; it's how the matching rules are measured and tuned on data
instead of on a handful of hand-picked products.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from selectolax.lexbor import LexborHTMLParser  # noqa: E402

from app import amazon, http, service  # noqa: E402
from app.models import Category, ProductSpec  # noqa: E402
from app.normalize import brands_match, kind_fits  # noqa: E402
from app.platforms.flipkart import Flipkart, identity_rows  # noqa: E402

BRANDS = {
    Category.SMARTPHONE: ["Apple iPhone", "Samsung Galaxy", "OnePlus", "Redmi", "Xiaomi", "POCO", "realme", "vivo", "OPPO",
                          "iQOO", "Motorola", "Nothing Phone", "Google Pixel", "Lava", "Tecno", "Infinix", "Honor"],
    Category.TELEVISION: ["Samsung", "LG", "Sony", "TCL", "Xiaomi", "OnePlus", "Hisense", "Acer", "Toshiba", "VU",
                          "Panasonic", "Philips", "Haier", "Thomson", "Kodak", "iFFALCON", "Redmi", "Coocaa", "Infinix"],
    Category.SNEAKERS: ["Nike", "adidas", "Puma", "Reebok", "Skechers", "New Balance", "ASICS", "Converse", "Vans", "Fila",
                        "Campus", "Sparx", "Red Tape", "Bata", "Woodland", "HRX", "Bacca Bucci", "ASIAN", "Liberty",
                        "Lotto", "Under Armour", "Jordan", "Kappa", "U.S. Polo Assn", "Tommy Hilfiger", "Levi's",
                        "Provogue", "Bxxy", "Shoexpress", "Roadster"],
    Category.TSHIRT: ["Nike", "adidas", "Puma", "U.S. Polo Assn", "Tommy Hilfiger", "Calvin Klein", "Levi's",
                      "Jack & Jones", "Allen Solly", "Van Heusen", "Peter England", "Louis Philippe", "Arrow", "Lacoste",
                      "Jockey", "Max", "Wrogn", "Highlander", "HRX", "The Souled Store", "Bewakoof", "Snitch",
                      "Raymond", "Indian Terrain", "Pepe Jeans", "Wrangler", "Lee", "Spykar", "Mufti", "Being Human",
                      "Superdry", "Fila", "Reebok", "Under Armour", "Dennis Lingo", "Lymio", "Nobero"],
}
KINDS = {
    Category.SMARTPHONE: ["5G smartphone", "smartphone 8GB 128GB", "phone 256GB", "5G mobile 6GB 128GB"],
    Category.TELEVISION: ["43 inch smart TV", "55 inch 4K TV", "32 inch smart TV", "50 inch 4K TV", "65 inch TV",
                          "75 inch TV"],
    Category.SNEAKERS: ["sneakers men", "sneakers women", "running shoes"],
    Category.TSHIRT: ["t-shirt men", "polo t-shirt men", "t-shirt women"],
}
JERSEYS = ["India cricket jersey", "IPL fan jersey", "Real Madrid jersey", "Manchester United jersey",
           "Barcelona jersey", "Argentina jersey", "Chennai Super Kings jersey", "Mumbai Indians jersey",
           "Royal Challengers jersey", "football jersey men", "India football jersey", "Manchester City jersey"]
PAGES_PER_PRODUCT = 10  # Flipkart product pages opened per product for ground truth

# Held-out set: different phrasings and brands the rules were never tuned on (--heldout)
HELDOUT = [
    # phones: price bands, features, other brands
    "best 5G phone under 15000", "phone under 25000 8GB RAM", "camera phone 256GB", "gaming phone 12GB RAM",
    "Samsung Galaxy A series", "iPhone 128GB", "Redmi Note 5G", "vivo Y series 5G", "OPPO Reno", "realme Narzo",
    "Motorola edge", "OnePlus Nord", "Lava Agni", "Tecno Pova", "Infinix GT", "Poco M series",
    # TVs: panel types, sizes, other brands
    "QLED TV 55 inch", "OLED TV", "Google TV 43 inch", "32 inch HD ready TV", "Mini LED TV 65 inch", "Fire TV 43 inch",
    "Samsung Neo QLED", "LG UHD TV", "Sony Bravia 3", "TCL QD Mini LED", "Hisense QLED", "Thomson TV 50 inch",
    "Acer Advanced I Series TV", "Panasonic TV 43 inch", "Vu GloLED", "Philips Ambilight",
    # sneakers: styles, colours, other brands
    "white sneakers men", "black running shoes women", "chunky sneakers women", "high top sneakers men",
    "slip on sneakers men", "kids sports shoes", "walking shoes women", "basketball shoes men",
    "Nike Air Max", "adidas Originals sneakers", "Puma running shoes women", "Skechers Go Run",
    "New Balance 530", "ASICS Gel Contend", "Reebok Classic", "Converse Chuck 70", "Vans Knu Skool",
    "Crocs sneakers", "Hush Puppies sneakers", "Mochi sneakers", "Neeman's sneakers", "Action shoes sneakers",
    # tees / polos / jerseys
    "oversized t-shirt men", "graphic t-shirt women", "striped polo t-shirt", "white polo men", "black t-shirt men",
    "dri fit t-shirt", "kids t-shirt boys", "henley t-shirt men", "v neck t-shirt women", "pack of 3 t-shirts",
    "Nike polo", "adidas t-shirt women", "Puma polo", "Tommy Hilfiger polo", "Lacoste t-shirt",
    "Gant polo", "Hugo Boss t-shirt", "Marks & Spencer t-shirt", "Rare Rabbit t-shirt", "Bonkers Corner t-shirt",
    "India cricket fan jersey 2026", "Kolkata Knight Riders jersey", "Gujarat Titans jersey", "Brazil football jersey",
    "Juventus jersey", "Liverpool jersey", "basketball jersey",
]


async def amazon_search(q: str, n: int) -> list[str]:
    r = await http.get("https://www.amazon.in/s", params={"k": q})
    out = []
    for d in LexborHTMLParser(r.text).css('div[data-component-type="s-search-result"]'):
        a = d.attributes.get("data-asin")
        if a and not d.css_first(".puis-sponsored-label-text") and a not in out:
            out.append(a)
    return out[:n]


async def record_product(asin: str) -> dict | None:
    try:
        src = await amazon.fetch_spec(f"https://www.amazon.in/dp/{asin}")
    except Exception as e:
        return {"asin": asin, "error": str(e)}
    rec = {"asin": asin, "source": src.model_dump(mode="json"), "platforms": {}}
    if src.category is None:
        return rec
    for platform in service.PLATFORMS[src.category]:
        entry = {"queries": [], "candidates": [], "rows": {}, "error": None}
        seen = set()
        try:
            for q in service.build_queries(src):
                entry["queries"].append(q)
                for c in await platform.search(q, src.category):
                    key = c.platform_id or c.url
                    if key not in seen:
                        seen.add(key)
                        entry["candidates"].append(c.model_dump(mode="json"))
            if isinstance(platform, Flipkart):
                same_brand = [c for c in entry["candidates"]
                              if brands_match(src.brand, c["brand"]) and kind_fits(src.category.value, c["kind"])]
                for c in same_brand[:PAGES_PER_PRODUCT]:
                    try:
                        page = await platform.product_page(ProductSpec(**c))
                        entry["rows"][c["platform_id"]] = identity_rows(page)
                    except Exception:
                        pass
        except Exception as e:
            entry["error"] = str(e)
        rec["platforms"][platform.name] = entry
    return rec


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-query", type=int, default=3)
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parent.parent / "eval" / "corpus.jsonl.gz"))
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--categories", default="", help="comma list, e.g. smartphone,television (default: all)")
    ap.add_argument("--heldout", action="store_true", help="use the held-out query set instead of brand x category")
    ap.add_argument("--exclude", nargs="*", default=[], help="corpus files whose products must not be re-recorded")
    args = ap.parse_args()

    wanted = {c.strip() for c in args.categories.split(",") if c.strip()}
    queries = list(HELDOUT) if args.heldout else None
    queries = queries or [f"{b} {k}" for cat, brands in BRANDS.items() if not wanted or cat.value in wanted
               for b in brands for k in KINDS[cat]] + ([] if wanted and "tshirt" not in wanted else JERSEYS)
    random.Random(7).shuffle(queries)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done: set[str] = set()
    for path in [out, *map(pathlib.Path, args.exclude)]:
        if path.exists():
            with gzip.open(path, "rt") as f:
                done |= {json.loads(line)["asin"] for line in f}
    print(f"{len(queries)} queries; {len(done)} products already in {out.name}", flush=True)

    asins: list[str] = []
    sem = asyncio.Semaphore(args.concurrency)

    async def find(q):
        async with sem:
            try:
                return await amazon_search(q, args.per_query)
            except Exception:
                return []
    for found in await asyncio.gather(*(find(q) for q in queries)):
        asins += [a for a in found if a not in asins and a not in done]
    if args.limit:
        asins = asins[:args.limit]
    print(f"{len(asins)} new products to record", flush=True)

    lock = asyncio.Lock()
    counter = {"n": 0}

    async def one(a):
        async with sem:
            rec = await record_product(a)
        async with lock:
            with gzip.open(out, "at") as f:
                f.write(json.dumps(rec) + "\n")
            counter["n"] += 1
            if counter["n"] % 25 == 0:
                print(f"  {counter['n']}/{len(asins)}", flush=True)
    await asyncio.gather(*(one(a) for a in asins))
    await http.close()
    print("done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
