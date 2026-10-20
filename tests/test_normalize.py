import pytest

from app.normalize import (
    brands_match, codes_match, colour_families, colours_match, garment_type, garment_types_compatible, parse_gender,
    identity_words, is_accessory, kind_fits, model_codes, model_words, parse_ram_gb, parse_screen_inches,
    parse_storage_gb,
)


@pytest.mark.parametrize("text,ram,storage", [
    ("SAMSUNG Galaxy S25 5G (12GB RAM, 256GB, Icyblue)", 12, 256),
    ("Samsung Galaxy S25 Ultra 5G (Titanium Whitesilver, 12GB RAM, 256GB Storage)", 12, 256),
    ("Apple iPhone 15 (Blue, 128 GB)", None, 128),
    ("8 GB RAM | 256 GB ROM | Expandable Upto 1 TB", 8, 256),
    ("Apple iPhone 15 Pro (1TB, Black Titanium)", None, 1024),
])
def test_ram_and_storage(text, ram, storage):
    assert parse_ram_gb(text) == ram
    assert parse_storage_gb(text) == storage


@pytest.mark.parametrize("text,inches", [
    ("Sony 139 cm (55 inches) BRAVIA 2", 55),
    ("SAMSUNG Crystal 4K 138 cm (55 inch) Ultra HD", 55),
    ("LG 108 cms (43 inches) NU87", 43),
    ("SONY BRAVIA 2 II 140 cm", 55.1),
])
def test_screen(text, inches):
    assert parse_screen_inches(text) == pytest.approx(inches, abs=0.1)


def test_brands():
    assert brands_match("U.S. POLO ASSN.", "U.S. Polo Assn.")
    assert brands_match("adidas", "ADIDAS Originals")
    assert brands_match("Redmi", "Xiaomi")
    assert not brands_match("Samsung", "Sony")


def test_colours():
    assert colour_families("Blue Wash") == ["blue"]  # not "ash" -> grey
    assert colour_families("CBLACK/FTWWHT/FTWWHT") == ["black", "white"]  # adidas codes
    assert colour_families("Titanium Whitesilver")[0] == "white"  # titanium is the finish
    assert colours_match("Jet Black", "black")[0]
    assert not colours_match("White", "Blue")[0]


@pytest.mark.parametrize("colour,primary", [
    ("LIGHT MARINE/BLACK-WHITE-BLACK", "blue"),  # Nike colourway: light marine shoe with black details
    ("Midnight Navy", "blue"),  # last colour word wins: navy, not "midnight" black
    ("Off-White", "white"),  # "Off" is a modifier, not a colour
    ("Black-Matte Silver", "black"),
])
def test_primary_colour(colour, primary):
    assert colour_families(colour)[0] == primary


def test_unknown_primary_colour_never_falls_back_to_secondary():
    assert colour_families("Zorbleflux/Black") == []
    assert not colours_match("Zorbleflux/Black", "Black")[0]
    assert not colours_match("LIGHT MARINE/BLACK-WHITE-BLACK", "Black")[0]


def test_model_codes():
    assert model_codes("K-55S25BM2") == ["K55S25BM2"]
    assert model_codes("MTP03HN/A") == ["MTP03HNA"]
    assert model_codes("39437101") == []  # digits alone could be anything...
    assert model_codes("39437101", allow_numeric=True) == ["39437101"]  # ...unless from a spec field


def test_codes_match_region_suffix_but_not_generation():
    assert codes_match(["43NU870BPLA"], ["43NU870"])  # Croma truncates the region code
    assert codes_match(["UA55DUE77AKLXL"], ["UA55DUE77AKXXL"])  # region variant
    assert not codes_match(["K55S25BM2"], ["K55S25B"])  # BRAVIA 2 II vs BRAVIA 2
    assert not codes_match(["UA55UE85AHULXL"], ["UA55UE83AHULXL"])  # UE85 vs UE83


def test_model_words_and_identity():
    assert identity_words(model_words("Apple iPhone 15 (128 GB) - Black", "Apple", "smartphone")) == {"15"}
    assert identity_words(model_words("Apple iPhone 15 Plus (Blue, 128 GB)", "Apple", "smartphone")) == {"15", "plus"}
    words = model_words("Samsung Galaxy S25 Ultra 5G AI Smartphone (Titanium, 12GB RAM, 256GB), 200MP | x",
                        "Samsung", "smartphone")
    assert words == ["galaxy", "s25", "ultra"]
    assert model_words("Puma | Smashic Comfort Casual Sneakers", "Puma", "sneakers") == ["smashic"]
    # "4K Ultra HD" must not look like the "Ultra" model
    assert "ultra" not in model_words("Sony 139 cm (55 inches) BRAVIA 2 4K Ultra HD Smart LED TV", "Sony",
                                      "television", keep_parens=True)


def test_garment_types():
    assert garment_type("U.S. Polo ASSN. Men's I638 V-Neck T-Shirt") == "tshirt/v-neck"  # brand isn't a polo
    assert garment_type("Allen Solly Men Polo Collar T-shirt") == "polo"
    assert not garment_types_compatible("tshirt/v-neck", "tshirt/round-neck")
    assert not garment_types_compatible("polo", "tshirt")
    assert garment_types_compatible("jersey", "tshirt/round-neck")


def test_accessories_and_kinds():
    assert is_accessory("SAMSUNG 25W Type C Fast Charger (Adapter Only)")
    assert is_accessory("Back Cover for Apple iPhone 15")
    assert not is_accessory("Samsung Crystal 4K 138 cm (55 inch) LED Smart TV with Voice Assistance Remote Control")
    assert not kind_fits("smartphone", "mobile-panel")
    assert kind_fits("tshirt", "kids-t-shirt") and kind_fits("sneakers", "shoe")


@pytest.mark.parametrize("colour,primary", [
    ("PHANTOM/CREAM II", "white"),  # Nike shade names
    ("Lt Orewood Brn/Soft Pearl-Tm Gold-White", "brown"),  # abbreviations: Lt = light, Brn = brown
    ("FOG/APL BUTR", "grey"),  # Campus
    ("PUTBEI/LINGRN/BLACK/WARSAN", "beige"),  # adidas colour codes
    ("Black(Red)", "black"),  # bracketed secondary colour
    ("Grey_1", "grey"), ("Medium Red1", "red"),  # Amazon variant suffixes
])
def test_brand_colourway_names(colour, primary):
    assert colour_families(colour)[0] == primary


def test_bracketed_model_name_is_kept():
    assert model_words("Nothing Phone (4b) 5G (White, 8GB RAM, 128GB Storage) | x", "Nothing", "smartphone") == ["4b"]
    assert model_words("Nothing Phone (4a) Pro (Silver, 128 GB)", "Nothing", "smartphone") == ["4a", "pro"]


def test_marketing_and_pattern_words_are_not_models():
    assert model_words("layasa Women's Sneaker Stylish Women Shoes White", "layasa", "sneakers") == []
    assert model_words("Puma Men's Solid Slim Fit Cotton Essential Polo T-Shirt for Regular wear", "Puma",
                       "tshirt") == ["essential"]
    assert "batman" in model_words("Bewakoof X DC Batman Men's Cotton Graphic Print Oversized Fit", "Bewakoof",
                                   "tshirt")
    assert "graphic" not in model_words("Bewakoof X DC Batman Men's Cotton Graphic Print", "Bewakoof", "tshirt")


def test_fabric_jersey_and_innerwear():
    assert garment_type("U.S. Polo ASSN. Men's I661 Round Neck Cotton Jersey Vest - Pack of 3") is None
    assert garment_type("adidas Men India T20 International Cricket Fan Jersey").startswith("jersey")


@pytest.mark.parametrize("text,gender", [
    ("Nike Unisex Kids Court Borough Low Recraft (GS) Sneakers", "kids"),
    ("Casual Sneaker Shoe for Mens & Boys", "men"),
    ("unisex-adult", "unisex"), ("mens", "men"), ("Puma Boys Tees", "kids"), ("adidas Womens Advantage", "women"),
])
def test_gender(text, gender):
    assert parse_gender(text) == gender


def test_style_code_suffixes():
    from app.normalize import style_codes_match
    assert style_codes_match("IO0461", "IO0461-100")  # colour suffix
    assert style_codes_match("BBMH9007U06", "BBMH9007U")  # Amazon appends the size
    assert style_codes_match("39437101", "394371-01")
    assert not style_codes_match("FX5501", "FX5502")  # another colourway
    assert not style_codes_match("ID8757", "ID8760")


@pytest.mark.parametrize("colour,family", [
    # not in the curated list: from the XKCD colour dataset (RGB -> family)
    ("Aubergine", "purple"), ("Dusty Rose", "pink"), ("Sea Green", "green"), ("Ochre", "brown"),
    ("Terracotta", "orange"), ("Steel Blue", "blue"), ("Light Dusty Rose", "pink"),
    # brand colour codes decoded by rule, not listed one by one
    ("TRUBLU", "blue"), ("GRETHR/CBLACK", "grey"), ("FTWWHT/CBLACK", "white"), ("CONAVY", "blue"),
])
def test_colours_beyond_the_curated_list(colour, family):
    assert colour_families(colour)[0] == family


def test_accessory_vs_product_listing_features():
    from app.normalize import brands_match, is_accessory
    assert not is_accessory("CAMPUS OGL-09 Casual Shoes for Women | Extra-Cushioned Memory Foam Insole", "sneakers")
    assert is_accessory("Shoe Laces for Sneakers, 120cm", "sneakers")
    assert is_accessory("Gel Insoles for Running Shoes", "sneakers")
    assert is_accessory("Back Cover for Apple iPhone 15", "smartphone")
    assert brands_match("Visio World", "VW")  # initials
