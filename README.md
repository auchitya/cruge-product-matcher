# Same product, other platforms

Paste an Amazon.in link to a **smartphone, TV, pair of sneakers or t-shirt/polo/jersey**. The app finds the same product on the other platforms and reports one of three results for each:

| Category | Searched on | Must match (besides brand + model) |
|---|---|---|
| Smartphones | Flipkart, Croma | RAM and storage |
| Televisions | Flipkart, Croma | Screen size |
| Sneakers | Flipkart, Myntra | Colour |
| T-shirts, polos, jerseys | Flipkart, Myntra | Colour |

● **In stock**: same product, buyable, with a link · ◐ **Out of stock**: same product, not buyable now, with a link · ○ **Not listed**: the platform doesn't sell it (plus the closest listings it rejected, and why).

The plain-language explanation of the matching is in [docs/HOW-MATCHING-WORKS.md](docs/HOW-MATCHING-WORKS.md) (also served at `/static/how-it-works.html`).

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8000
# open http://localhost:8000
```

Or with Docker: `docker build -t same-product . && docker run -p 8000:8000 same-product`.

From the terminal: `.venv/bin/python scripts/try.py B0CHX1W1XY B0F7X5FC43` (ASINs or full links).

API: `POST /api/match {"url": "https://www.amazon.in/dp/…"}` returns the Amazon spec plus, per platform, the status, the matched listing, every check with both sides' values, and the near misses.

Tests (offline, run against saved Amazon/Flipkart/Croma/Myntra responses): `.venv/bin/python -m pytest`

## How it works

```
Amazon link ──► amazon.py         read the product page → ProductSpec (brand, category, model words,
                                   model/style number, RAM, storage, screen, colour, gender, garment type)
            ──► service.py        pick platforms for the category, build 1–2 search queries (specific → loose)
            ──► platforms/*.py    search each platform in parallel → candidate ProductSpecs
            ──► matcher.py        run named checks on every candidate; match only if all required checks pass
            ──► service.py        fashion: open top listings to look for Amazon's style code
                                   rank matches (same colour first), check stock on the best few,
                                   prefer one you can buy → In stock / Out of stock / Not listed / Couldn't check
```

### Getting the data (no headless browser)

| Platform | Source | Stock signal |
|---|---|---|
| Amazon | product page HTML: overview/tech-spec/detail tables, breadcrumbs, byline | (input only) |
| Flipkart | search page's embedded `window.__INITIAL_STATE__` JSON | card `availability.displayState`; product page `availabilityStatus` for fashion |
| Croma | the site's own JSON search API (`api.croma.com/searchservices`) | `pdp/deliveryoption?pinCode=` for Mumbai/Delhi/Bengaluru (any = in stock) |
| Myntra | listing page's embedded `window.__myx` JSON | product page `flags.outOfStock` / all sizes unavailable |

**Hosting note.** From cloud servers (Render, and any other free host), Myntra answers with a fake "Site Maintenance" page and Flipkart's product pages answer HTTP 429; Amazon, Flipkart search and Croma work. Set `PROXY_URL` (a residential proxy, `http://user:pass@host:port`) and only those blocked requests go through it, to keep proxy bandwidth small (Myntra via its ~60 KB JSON API instead of the ~500 KB page). `PROXY_SCOPE=myntra` sends only Myntra through it (~0.1 MB per lookup; Flipkart then answers from search names without product-page proof), and `PROXIED_PAGE_CHECKS` (default 10, the same as direct) caps how many ~1.4 MB Flipkart product pages a lookup opens through the proxy. Pages are opened three at a time, in parallel, and the lookup stops at the first batch that proves the match, so a typical fashion lookup opens 3–6 pages and takes ~6–14 s through the proxy instead of ~20–30 s for all ten at once. Set it to 3 to stretch a small proxy allowance, at the cost of some style-code matches. `GET /api/diag` shows, from the server, what each site returns and whether it went through the proxy.

Croma sits behind Akamai, which blocks normal HTTP clients and headless Chrome. All requests go through [`curl_cffi`](https://github.com/lexiforest/curl_cffi) with a Chrome TLS fingerprint, which is enough for every platform without running a browser. A full lookup takes ~3–5 s.


### Matching rules (`app/matcher.py`)

**Which category is it?** Amazon's breadcrumb *leaf* decides ("Smartphones", "Smart Televisions", "Sneakers", "Polos"). Anything else is rejected with a message, even inside a matching department: "Formal Shoes", "Sandals & Floaters", "Boots", "Shirts" (formal), "Basic Cases", "Power Banks", "Tablets", "TV Wall & Ceiling Mounts", "Projectors", innerwear vests. Without breadcrumbs, Amazon's "Generic Name" field and then the title are used, with a list of words that rule a product out.

Every candidate gets a list of named checks; the UI shows them as a table ("Why we think it's the same product").

- **Brand**: normalised and alias-aware (`U.S. POLO ASSN.` = `U.S. Polo Assn.`, `Redmi` = `Xiaomi`).
- **Category**: the platform's own label must fit (Flipkart files phone back-panels under `mobile-panel`, not `mobile`; Myntra files sandals under "Sandals", not "Casual Shoes"), accessory titles ("charger", "back cover") are rejected, and for sneakers so are formal shoes, sandals, sliders and boots.
- **Model, electronics**: if both sides carry a model number, they must agree. A letters-only tail is a region code (`43NU870` ≈ `43NU870BPLA`); a tail with a digit is a different generation (`K-55S25B` ≠ `K-55S25BM2`). Otherwise the model's *identity words* (numbers like `15`/`s25`/`13r` and modifiers like `pro`/`plus`/`ultra`/`fe`) must be identical, and the product-line word must agree (`FX Pro` ≠ `X Pro`). Marketing text after `|`, `,`, `with` and phrases like "4K **Ultra** HD" are stripped first.
- **Model, fashion**: the distinctive Amazon model words must appear (none may be missing out of 1–3, one out of 4–6), with light stemming (`tipped` ≈ `tipping`). Marketing and pattern words ("stylish", "for regular wear", "graphic print") don't count as model words. A model "name" that's really a part number (`Rsl1448a-10`) is ignored. If Amazon gives no model name, a match **requires** the style code (`IH1476`, `KS9354`), found in the listing's own Style Code / Article Number fields on Flipkart.
- **Product identifiers, both ways** (Flipkart): its product pages state each listing's style code (fashion) or model number (TVs). The app opens the most promising listings (always including any it's about to show) and compares. Same identifier as Amazon proves the match, even when Flipkart's title is vague ("ADIDAS Striped Men V Neck Blue T-Shirt" is the official India jersey `KS9354`) or contradicts Amazon's ("Printed" vs "Solid"). Fashion allows a short size/colour suffix (`IO0461` = `IO0461-100`, `BBMH9007U` = `BBMH9007U06`); TVs use the strict generation rule. A *different* identifier (`FX5502` vs Amazon's `FX5501`) rejects the listing however similar the title. If the proven listing is sold out, the answer is "Out of stock": a look-alike in stock is never substituted.
- **Variants**: a listing whose extra name words outnumber Amazon's model words is a different line ("Club Tee" ≠ "Jordan Flight Club Tee"); kits from different seasons differ (Real Madrid 25/26 ≠ 26/27); kids' shoes ≠ adult shoes.
- **RAM/storage** (phones): exact. Implausible figures (RAM ≥ storage or > 32 GB, storage < 16 GB) are treated as data-entry errors and ignored.
- **Screen size** (TVs): within 1″ (139 cm and 140 cm are both "55-inch").
- **Colour** (fashion): same name, or the same primary colour family (`Jet Black` = `Black`). Brand colourway names are understood: "Light **Marine**" is blue, "Midnight **Navy**" is navy, Nike "PHANTOM/CREAM", "Lt Orewood **Brn**", adidas `CBLACK/FTWWHT`, `PUTBEI/LINGRN`. If the main colour is a word it doesn't know, the colour can't be confirmed; a secondary colour never stands in for it. For phones and TVs colour is a *preference* (it ranks results), because the brief defines the same phone by RAM and storage.
- **Gender**, **garment type** and **pattern** (fashion) must not clash: a polo is never a t-shirt; V-neck ≠ round-neck; jersey ≈ t-shirt; solid ≠ striped ≠ printed; a "kids" title beats the platform's gender field.
- **Condition**: renewed/refurbished listings are rejected.

Confidence is **high** for a model-number/style-code match or an exact model-name match, **medium** when names agree with minor gaps.

## How we know it works

Rules tuned on a handful of hand-picked products overfit, so the matcher is measured on a crawled corpus instead.

```bash
.venv/bin/python scripts/build_corpus.py      # live crawl -> eval/corpus.jsonl.gz (resumable)
.venv/bin/python scripts/evaluate.py --audit 30  # offline replay + scores + examples of every error
.venv/bin/python scripts/learn_vocab.py       # re-learn generic words from the corpus
```

- **The corpus** (`eval/corpus.jsonl.gz`): **589 Amazon products → 1,178 platform lookups**, found by searching ~100 brands × each category (phones from 17 brands, TVs from 19 sizes/brands, sneakers from 30 brands, tees/polos/jerseys from 37 brands + 12 team-jersey searches). For every lookup it stores every candidate listing the platform returned, plus Flipkart's identifier rows (Style Code / Article Number / Model Number) for the top same-brand listings.
- **Ground truth without hand labels**: style codes (fashion, plus same main colour) and model numbers (TVs) on both sides. Phones are checked by eye on random samples, because phone model numbers encode the colour, which the brief says doesn't matter.
- **The replay** runs the *real* decision code (`service.check_platform`) on the recorded candidates, so it measures exactly what a user would see.

**Tuning set** (589 products; the rules were developed against it):

| | Verified correct | Verified **wrong** | Missed (platform has it, we said "not listed") |
|---|---|---|---|
| Sneakers | 64 | **0** | 0 |
| T-shirts / polos / jerseys | 28 | **0** | 1 |
| TVs | 63 | **0** | 0 |
| Phones (35 random matches checked by eye) | 35 | **0** | n/a |

**Held-out set** (`eval/heldout.jsonl.gz`, 170 *new* products from 84 searches the rules were never tuned on: new brands such as Mochi, Neeman's, Crocs, Gant, Rare Rabbit, Lava, Tecno, Vu, and new phrasings such as "white sneakers men" or "QLED TV 55 inch"). Scored with the rule code frozen (checked by hashing `app/` before and after the crawl):

| | Result |
|---|---|
| Code-verified matches (TVs 11, sneakers 20, tees 2) | **33 / 33 correct**, 0 missed |
| Phone matches checked by eye | **19 / 19 correct** |
| Fashion matches **without** a product code, checked by eye | **18 / 21 correct** |

The three held-out errors were all no-code fashion: Neeman's "Everyday Basic" matched "Elevated Basics" / "Tread Basics" on both platforms, and a no-name "High-Top" sneaker matched a different design. The high-top case is now fixed (a two-word generic phrase like "high top" is not a model name). The Neeman's case is a known limit: a one-word model name where the other platform adds a *different* name word. The obvious rule ("no extra name words allowed") was tested on the data and rejected, because it lost 11 correct matches such as Nike Winflo 11 → "Winflo 11 **Road** Running". **So for fashion matches with medium confidence and no product code, expect roughly one in seven to be a near-miss variant on unfamiliar brands.** Code-proven and high-confidence matches held at 100%.

Matches that can't be verified (most phones; fashion on Myntra, which shows no codes) are audited by eye from random samples (`--audit`). `tests/test_corpus.py` replays both sets on every test run (~12 s) and fails on any verifiably wrong match, or if verified matches drop or misses rise, so a rule that fixes one product but breaks others is caught.

**Learned from data vs written by hand.** What's generic is learned rather than typed in:
- *Generic title words*: `scripts/learn_vocab.py` counts how many **different brands** use each word in a category over ~55,000 titles. Words used by 12+ brands ("breathable", "chunky", "raglan", "suede") describe a kind of product, so they aren't evidence of a model name. They still have to be present if Amazon names them ("Court Vision Lo **Suede**").
- *Colours*: ~950 colour names from the XKCD colour survey (CC0), mapped to colour families from their RGB values (`scripts/build_colours.py` → `app/data/colours.json`), plus a general rule for brand colour codes (3-letter abbreviations at either end: `FTW`**`WHT`**, `PUT`**`BEI`**, **`GRE`**`THR`).
- *What's still curated*: the category vocabulary (accessory/footwear words, garment types), unit parsing and ~13 brand-alias groups. These are domain rules, not product lists.

## Design decisions

- **Precision over recall.** A wrong "In stock" link is worse than an honest "Not listed", so every required check must pass. When nothing matches, the closest rejected listings are shown with the reason, so a human can make the call.
- **Explainable, not a black box.** It's deterministic rules rather than an LLM judge: every decision is a list of checks you can read, test and argue with. (An LLM tie-breaker for vague fashion titles would be an easy addition behind the same `Check` interface.)
- **Errors aren't "Not listed".** If a platform blocks or times out, the result is "Couldn't check".
- **Stock preference.** If several listings match (colour variants, duplicate SKUs), the best few are opened and an in-stock one wins.

## Known limits

- **Vague apparel.** A t-shirt whose Amazon page has no model name and whose style code isn't on the other platform will be "Not listed". Myntra pages don't show style codes, so on Myntra these items rely on the name alone.
- **Colour families are coarse.** "Blue Wash" (light) and a navy shirt labelled "Blue" both count as blue.
- **One-word fashion names are ambiguous** (measured above: the main source of errors). "Bewakoof X DC Batman … Graphic Print Tee" has one distinctive word; Myntra sells several Batman tees, so the pick (medium confidence) depends on Myntra's ranking.
- **One extra word isn't penalised.** Platforms add words freely ("Textile", "Lace-Up", "Road Running"), so a variant with one extra name word (Converse "Chuck Taylor All Star **Malden Slip On**") can still match the plain model on Myntra, which shows no style codes.
- **Amazon's own data is sometimes wrong** (a women's shoe filed under Department: mens; two different article numbers on one page). The title wins on gender; every listed code is tried.
- **Search results vary run to run** on Myntra and Flipkart, so a listing that only appears on some searches can flip between "matched" and "not listed".
- **Myntra search hides out-of-stock styles**, so a sold-out Myntra item usually shows as "Not listed".
- **Croma stock is per pincode.** Defaults: Mumbai, Delhi, Bengaluru (`CROMA_PINCODES=400049,110001,560001`).
- **Scraping is brittle by nature.** Each platform adapter is ~100 lines behind one interface (`search`, `check_stock`, `product_page`), and the saved fixtures make breakages show up in tests.
- Results are cached for 10 minutes per ASIN.

## Layout

```
app/
  main.py          FastAPI: POST /api/match, static UI
  service.py       orchestration: queries, ranking, stock, identifier (style code / model number) proof
  matcher.py       the checks
  normalize.py     text → facts: sizes, colours, model words, model numbers, garment types
  amazon.py        Amazon page → ProductSpec
  platforms/       flipkart.py, croma.py, myntra.py (+ base.py interface)
  http.py          shared curl_cffi session with retries
  data/            colours.json (XKCD colours -> families), generic_words.json (learned from the corpus)
static/            index.html (the app), how-it-works.html
docs/              HOW-MATCHING-WORKS.md
tests/             163 offline tests (incl. replay of both corpora) + saved Amazon/Flipkart/Croma/Myntra pages
eval/              corpus.jsonl.gz (589 products, tuning) + heldout.jsonl.gz (170 products, never tuned on)
scripts/           try.py (CLI), build_corpus.py, evaluate.py, learn_vocab.py, build_colours.py, fixture savers
```
