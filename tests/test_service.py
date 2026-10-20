"""The orchestration: three statuses (+ error), stock preference, style-code upgrade. No network."""
import asyncio

from app import service
from app.models import Category, ProductSpec, Status
from app.platforms.base import Platform

SRC = ProductSpec(title="Apple iPhone 15 (128 GB) - Black", brand="Apple", category=Category.SMARTPHONE,
                  storage_gb=128, colour="Black")


def phone(title, storage=128, colour="Black", in_stock=None, pid=None):
    return ProductSpec(title=title, brand="Apple", category=Category.SMARTPHONE, storage_gb=storage,
                       colour=colour, in_stock=in_stock, url=f"https://x/{pid or title}", platform_id=pid or title)


class FakePlatform(Platform):
    name = key = "Fake"

    def __init__(self, results, stock=None, pages=None, fail=False):
        self.results, self.stock, self.pages, self.fail = results, stock or {}, pages or {}, fail

    async def search(self, query, category):
        if self.fail:
            raise RuntimeError("blocked")
        return list(self.results)

    async def check_stock(self, spec):
        return self.stock.get(spec.platform_id, spec.in_stock)

    async def product_page(self, spec):
        return self.pages.get(spec.platform_id)


def run(platform, src=SRC):
    return asyncio.run(service.check_platform(platform, src))


def test_in_stock_preferred_over_out_of_stock():
    p = FakePlatform([phone("Apple iPhone 15 (Black, 128 GB)", pid="a", in_stock=False),
                      phone("Apple iPhone 15 (Blue, 128 GB)", colour="Blue", pid="b", in_stock=True)])
    r = run(p)
    assert r.status == Status.IN_STOCK and r.match.platform_id == "b"
    assert any("different colour" in n for n in r.notes)


def test_out_of_stock_when_no_match_is_buyable():
    r = run(FakePlatform([phone("Apple iPhone 15 (Black, 128 GB)", pid="a", in_stock=False)]))
    assert r.status == Status.OUT_OF_STOCK and r.match.url


def test_not_listed_shows_near_misses():
    r = run(FakePlatform([phone("Apple iPhone 15 Plus (Black, 128 GB)"), phone("Apple iPhone 15 (Black, 256 GB)",
                                                                                 storage=256)]))
    assert r.status == Status.NOT_LISTED and r.match is None and len(r.near_misses) == 2


def test_platform_failure_is_an_error_not_not_listed():
    r = run(FakePlatform([], fail=True))
    assert r.status == Status.ERROR and "blocked" in r.error


def test_style_code_upgrades_a_vague_fashion_listing():
    src = ProductSpec(title="adidas Men Polyester Fitted T-Shirt", brand="adidas", category=Category.TSHIRT,
                      colour="Blue", gender="men", product_type="tshirt", model_codes=["FJ9217"])
    shirt = ProductSpec(title="ADIDAS Solid Men Round Neck Blue T-Shirt", brand="ADIDAS", category=Category.TSHIRT,
                        colour="Blue", gender="men", product_type="tshirt/round-neck", url="https://x/1",
                        platform_id="1")
    p = FakePlatform([shirt], stock={"1": True}, pages={"1": "<td>Style Code</td><td>FJ9217</td>"})
    r = run(p, src)
    assert r.status == Status.IN_STOCK and r.confidence == "high"
    assert any(c.name == "Style code" for c in r.checks)

    r = run(FakePlatform([shirt], stock={"1": True}, pages={"1": "<td>Style Code</td><td>XX0000</td>"}), src)
    assert r.status == Status.NOT_LISTED


def test_queries_most_specific_first():
    qs = service.build_queries(SRC)
    assert qs[0] == "Apple iphone 15 128 GB" and qs[1] == "Apple iphone 15"


SHOE_SRC = ProductSpec(title="adidas Mens Grand Court 3.0 Sneaker", brand="adidas", category=Category.SNEAKERS,
                       colour="CBLACK/FTWWHT", gender="men", model_codes=["IH1476"])


def shoe(title, pid, in_stock):
    return ProductSpec(title=title, brand="ADIDAS", category=Category.SNEAKERS, colour="Black", gender="men",
                       url=f"https://x/{pid}", platform_id=pid, in_stock=in_stock)


class CodePlatform(FakePlatform):
    def listed_codes(self, page, category=None):
        return [page.split(":")[1]] if page and ":" in page else []


def test_proven_product_out_of_stock_is_not_swapped_for_a_lookalike():
    exact = shoe("ADIDAS GRAND COURT 3.0 Sneakers For Men", "exact", in_stock=False)
    lookalike = shoe("ADIDAS GRAND COURT 3.0 Classic Sneakers For Men", "other", in_stock=True)
    p = CodePlatform([lookalike, exact], pages={"exact": "Style Code:IH1476", "other": ""})
    r = run(p, SHOE_SRC)
    assert r.status == Status.OUT_OF_STOCK and r.match.platform_id == "exact"


def test_listing_with_a_different_style_code_is_rejected():
    base = shoe("ADIDAS GRAND COURT BASE 3.0 IKD Sneakers For Men", "base", in_stock=True)
    r = run(CodePlatform([base], pages={"base": "Style Code:LA1520"}), SHOE_SRC)
    assert r.status == Status.NOT_LISTED
    assert any(c.name == "Style code" and not c.ok for c in r.near_misses[0].checks)
