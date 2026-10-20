from app.models import Category
from app.platforms import croma, flipkart, myntra


def test_flipkart_search_parse(platform_json):
    items = flipkart.parse_search(platform_json("flipkart_search_iphone15"), Category.SMARTPHONE)
    assert items
    first = items[0]
    assert first.brand == "Apple" and first.storage_gb in (128, 256, 512)
    assert first.url.startswith("https://www.flipkart.com/") and "pid=" in first.url and "srno" not in first.url
    assert first.kind == "mobile"
    assert first.in_stock is not None  # electronics cards carry availability


def test_flipkart_fashion_cards(platform_json):
    items = flipkart.parse_search(platform_json("flipkart_search_smashic"), Category.SNEAKERS)
    assert items and all(i.kind for i in items)
    assert any(i.colour for i in items)  # from the "White , 10" subtitle
    assert all(i.in_stock is None for i in items)  # fashion cards don't say; checked on the product page


def test_flipkart_product_page_stock():
    assert flipkart.parse_stock_from_product_page('{"availabilityStatus":"IN_STOCK"}') is True
    assert flipkart.parse_stock_from_product_page('{"availabilityStatus":"OUT_OF_STOCK"}') is False
    assert flipkart.parse_stock_from_product_page('"availability":"https://schema.org/OutOfStock"') is False


def test_croma_search_parse(platform_json):
    items = croma.parse_search(platform_json("croma_search_s24"), Category.SMARTPHONE)
    s24 = [i for i in items if "S24 5G (8GB RAM, 256GB" in i.title]
    assert s24 and s24[0].ram_gb == 8 and s24[0].storage_gb == 256 and s24[0].colour
    assert s24[0].url.startswith("https://www.croma.com/") and s24[0].platform_id


def test_myntra_search_parse(platform_json):
    items = myntra.parse_search(platform_json("myntra_search_smashic"), Category.SNEAKERS)
    assert items and all(i.url.startswith("https://www.myntra.com/") for i in items)
    assert all(i.colour and i.brand for i in items)


def test_myntra_stock():
    assert myntra.parse_stock_from_product_page({"pdpData": {"flags": {"outOfStock": True}}}) is False
    assert myntra.parse_stock_from_product_page(
        {"pdpData": {"flags": {}, "sizes": [{"available": False}, {"available": False}]}}) is False
    assert myntra.parse_stock_from_product_page(
        {"pdpData": {"flags": {}, "sizes": [{"available": False}, {"available": True}]}}) is True


def test_flipkart_price_is_what_you_pay_not_mrp(platform_json):
    # Fashion cards only have a `prices` list: struck-through M.R.P. + the real price
    shoes = flipkart.parse_search(platform_json("flipkart_search_smashic"), Category.SNEAKERS)
    smashic = next(s for s in shoes if s.title == "PUMA Smashic Sneakers For Men")
    assert smashic.price == 1659  # not the ₹4,499 M.R.P.
    assert all(s.price for s in shoes)
    phones = flipkart.parse_search(platform_json("flipkart_search_iphone15"), Category.SMARTPHONE)
    assert all(p.price for p in phones)
    assert next(p for p in phones if p.title == "Apple iPhone 15 (Blue, 128 GB)").price == 67999  # not ₹74,900


def test_flipkart_identity_text_only_reads_this_products_codes():
    page = ('{"label_1":{"value":{"text":["KS9354"]}},"label_0":{"value":{"text":"Style Code"}}}'
            '<meta name="Description" content="ADIDAS Striped Men V Neck Blue T-Shirt">'
            '{"similarProducts":[{"styleCode":"ZZ1111"}]}')
    text = flipkart.identity_text(page)
    assert "KS9354" in text and "ZZ1111" not in text
