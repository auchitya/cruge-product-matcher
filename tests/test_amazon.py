import pytest

from app.amazon import extract_asin, parse_product_page
from app.models import Category


@pytest.mark.parametrize("url,asin", [
    ("https://www.amazon.in/Apple-iPhone-15-128-GB/dp/B0CHX1W1XY/ref=sr_1_1?crid=2", "B0CHX1W1XY"),
    ("https://www.amazon.in/dp/B0CHX1W1XY", "B0CHX1W1XY"),
    ("https://www.amazon.in/gp/product/B0CHX1W1XY?th=1", "B0CHX1W1XY"),
    ("https://amzn.in/d/abc123", None),  # short link: resolved by following the redirect
])
def test_extract_asin(url, asin):
    assert extract_asin(url) == asin


@pytest.mark.parametrize("asin,expect", [
    ("B0CHX1W1XY", dict(category=Category.SMARTPHONE, brand="Apple", storage_gb=128, ram_gb=None, colour="Black")),
    ("B0H2J3PRKV", dict(category=Category.SMARTPHONE, brand="Samsung", storage_gb=256, ram_gb=12, colour="Icyblue")),
    ("B0FZT1LXPZ", dict(category=Category.SMARTPHONE, brand="OnePlus", storage_gb=256, ram_gb=12)),
    ("B0DGJH8RYG", dict(category=Category.SMARTPHONE, brand="Apple", storage_gb=128, ram_gb=None)),  # bad RAM field
    ("B0F7X5FC43", dict(category=Category.TELEVISION, brand="Sony", screen_inches=55)),
    ("B0GTZ9TSDJ", dict(category=Category.TELEVISION, brand="LG", screen_inches=43)),
    ("B0F2FFQPYW", dict(category=Category.SNEAKERS, brand="adidas", gender="men")),
    ("B098PC5X7Y", dict(category=Category.SNEAKERS, brand="Nike")),  # premium layout: brand from logo alt
    ("B0BFX1ND5G", dict(category=Category.TSHIRT, brand="PUMA", product_type="polo", colour="Blue Wash")),
    ("B07S15T5TT", dict(category=Category.TSHIRT, product_type="tshirt/v-neck", colour="White")),
])
def test_parse_product_page(amazon_html, asin, expect):
    spec = parse_product_page(amazon_html(asin))
    for k, v in expect.items():
        assert getattr(spec, k) == v, k


def test_tv_model_codes(amazon_html):
    assert "K55S25BM2" in parse_product_page(amazon_html("B0F7X5FC43")).model_codes
    assert "43NU870BPLA" in parse_product_page(amazon_html("B0GTZ9TSDJ")).model_codes


def test_fashion_style_codes(amazon_html):
    assert parse_product_page(amazon_html("B0F2FFQPYW")).model_codes == ["IH1476"]
    assert parse_product_page(amazon_html("B0BSLLDJRC")).model_codes == ["39437101"]


@pytest.mark.parametrize("asin,price", [
    ("B0GH6PMXR9", 3247),  # hidden price text empty: must read visible digits, not the ₹6,495 M.R.P.
    ("B0DGJH8RYG", 76999),  # not the ₹89,900 M.R.P.
    ("B0BFX1ND5G", 829),  # not the ₹2,299 M.R.P.
])
def test_price_is_selling_price_not_mrp(amazon_html, asin, price):
    assert parse_product_page(amazon_html(asin)).price == price


IN_SCOPE = {
    Category.SMARTPHONE: ["B0CHX1W1XY", "B0DSKL9MQ8", "B0H2J3PRKV", "B0FZT1LXPZ", "B0GX1W2CLZ", "B0DGJH8RYG",
                          "B0CS69QQTG", "B07HGJJ58K", "B0H8PRXFLY", "B0HBCLFSZ1", "B0FDBB2VRC"],
    Category.TELEVISION: ["B0F3JKY28G", "B0F7X5FC43", "B0GTZ9TSDJ", "B0GYRRLP87", "B0GVPGQYFD"],
    Category.SNEAKERS: ["B0BSLLDJRC", "B0F2FFQPYW", "B098PC5X7Y", "B0GH6PMXR9", "B09WYD48F1", "B0C8TJ6SXK",
                        "B000LFG274", "B09HKVQ29F", "B0HJMDWBKJ"],
    Category.TSHIRT: ["B0BFX1ND5G", "B07XL2MWPR", "B06Y2CH63N", "B07S15T5TT", "B0G58WYLMQ", "B0BX3VRHM9"],
}
OUT_OF_SCOPE = {
    "B0BHW77CZY": "formal shirt",  # crumb leaf "Shirts" under "T-shirts, Polos & Shirts"
    "B096BFVSFG": "formal shoes", "B095X58264": "sandals", "B0HGRNNMJC": "flip-flops", "B0FP23ZPHW": "heels",
    "B0DJQXKJ3B": "boots", "B07S28JYQZ": "innerwear vest (title says 'Cotton Jersey')",
    "B0HKW4MRFW": "iPhone back cover", "B0D96HMLYX": "power bank", "B0H229NR2Z": "phone charger",
    "B0G1C13SB3": "tablet", "B0CYQ6TJN8": "TV wall mount", "B0GNHM9YKM": "projector",
}


@pytest.mark.parametrize("asin,category", [(a, c) for c, asins in IN_SCOPE.items() for a in asins])
def test_in_scope_categories(amazon_html, asin, category):
    assert parse_product_page(amazon_html(asin)).category == category


@pytest.mark.parametrize("asin,what", OUT_OF_SCOPE.items())
def test_out_of_scope_products_are_rejected(amazon_html, asin, what):
    assert parse_product_page(amazon_html(asin)).category is None, what


def test_inconclusive_breadcrumb_falls_back_to_product_type(amazon_html):
    # "Supporters' Gear > Cricket" names no category; Generic Name says T-Shirt
    assert parse_product_page(amazon_html("B0GR9VY4SM")).category == Category.TSHIRT
    assert parse_product_page(amazon_html("B0D2DC3YNT")).category is None  # Puma "Softride" is a slipper
    assert parse_product_page(amazon_html("B0GKPXRH2K")).category is None  # tank top filed under Vests


def test_department_decides_gender(amazon_html):
    assert parse_product_page(amazon_html("B0DBD9KHVF")).gender == "men"
    assert parse_product_page(amazon_html("B0C861C9MS")).gender == "kids"


def test_unknown_colour_falls_back_to_title_colour(amazon_html):
    assert parse_product_page(amazon_html("B0F1XGMJW4")).colour.lower() == "blue"  # field says DUPE/CBLACK/FTWWHT


def test_title_gender_beats_wrong_department(amazon_html):
    # Title "Skechers Women Uno Night Shades" but Department: mens
    assert parse_product_page(amazon_html("B081K4H8QC")).gender == "women"
