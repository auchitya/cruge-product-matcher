"""The matcher's decisions on the cases that are easy to get wrong."""
from app.matcher import evaluate
from app.models import Category, ProductSpec

PHONE = Category.SMARTPHONE
TV = Category.TELEVISION
SHOES = Category.SNEAKERS
TEE = Category.TSHIRT


def spec(title, category, **kw):
    return ProductSpec(title=title, category=category, **kw)


def decide(src, cand):
    result, confidence = evaluate(src, cand)
    failed = [c.name for c in result.checks if c.required and not c.ok]
    return result.matched, failed, confidence


IPHONE15 = spec("Apple iPhone 15 (128 GB) - Black", PHONE, brand="Apple", storage_gb=128, colour="Black")
S25 = spec("Samsung Galaxy S25 5G (Icyblue, 12GB RAM, 256GB Storage) | Snapdragon", PHONE,
           brand="Samsung", ram_gb=12, storage_gb=256, colour="Icyblue")


def test_same_phone_different_colour_still_matches():
    ok, failed, conf = decide(IPHONE15, spec("Apple iPhone 15 (Blue, 128 GB)", PHONE, brand="Apple",
                                             storage_gb=128, colour="Blue"))
    assert ok and conf == "high"


def test_plus_and_pro_are_different_phones():
    for title in ("Apple iPhone 15 Plus (Black, 128 GB)", "Apple iPhone 15 Pro (Black Titanium, 128 GB)"):
        ok, failed, _ = decide(IPHONE15, spec(title, PHONE, brand="Apple", storage_gb=128))
        assert not ok and failed == ["Model"]


def test_storage_and_ram_must_match():
    ok, failed, _ = decide(IPHONE15, spec("Apple iPhone 15 (Black, 256 GB)", PHONE, brand="Apple", storage_gb=256))
    assert failed == ["Storage"]
    ok, failed, _ = decide(S25, spec("SAMSUNG Galaxy S25 5G (8GB RAM, 256GB, Icyblue)", PHONE, brand="Samsung",
                                     ram_gb=8, storage_gb=256))
    assert failed == ["RAM"]


def test_accessory_is_not_the_phone():
    ok, failed, _ = decide(IPHONE15, spec("Back Cover for Apple iPhone 15 (128 GB)", PHONE, brand="Apple",
                                          storage_gb=128))
    assert not ok and "Category" in failed
    ok, failed, _ = decide(IPHONE15, spec("Apple iPhone 15 (Black, 128 GB)", PHONE, brand="Apple", storage_gb=128,
                                          kind="mobile-panel"))
    assert not ok and "Category" in failed


def test_refurbished_is_not_new():
    ok, failed, _ = decide(IPHONE15, spec("Apple iPhone 15 (Black, 128 GB) (Renewed)", PHONE, brand="Apple",
                                          storage_gb=128))
    assert failed == ["Condition"]


SONY = spec("Sony 139 cm (55 inches) Smartchoice BRAVIA 2M2 Series 4K Ultra HD Smart LED Google TV K-55S25BM2", TV,
            brand="Sony", screen_inches=55, model_codes=["K55S25BM2"])


def test_tv_same_model_number():
    ok, _, conf = decide(SONY, spec("SONY BRAVIA 2 II 140 cm (55 inch) 4K Ultra HD LED Smart Google TV", TV,
                                    brand="Sony", screen_inches=55.1, model_codes=["K55S25BM2"]))
    assert ok and conf == "high"


def test_tv_previous_generation_rejected():
    ok, failed, _ = decide(SONY, spec("SONY Bravia 2 138.8 cm (55 inch) Ultra HD (4K) LED Smart Google TV", TV,
                                      brand="Sony", screen_inches=54.6, model_codes=["K55S25B"]))
    assert failed == ["Model"]


def test_tv_screen_size_must_match():
    ok, failed, _ = decide(SONY, spec("SONY BRAVIA 2 II 164 cm (65 inch)", TV, brand="Sony", screen_inches=65,
                                      model_codes=["K65S25BM2"]))
    assert "Screen size" in failed


def test_tv_product_line_without_codes():
    fx = spec("Xiaomi (108 cm) 43 inch FX Pro 4K QLED Smart | HDR10+", TV, brand="Xiaomi", screen_inches=43)
    ok, failed, _ = decide(fx, spec("Xiaomi X Pro 109 cm (43 inch) 3 Star QLED 4K Ultra HD Google TV", TV,
                                    brand="Xiaomi", screen_inches=43))
    assert failed == ["Model"]  # "X Pro" is not "FX Pro"


NIKE = spec("Nike Mens Court Vision Lo NN Sneakers", SHOES, brand="Nike", colour="WHITE/BLACK-WHITE", gender="men")


def test_sneaker_same_model_and_colour():
    ok, _, conf = decide(NIKE, spec("Nike Men Court Vision Low Sneakers", SHOES, brand="Nike", colour="White",
                                    gender="men"))
    assert ok and conf == "high"


def test_sneaker_different_line_rejected():
    ok, failed, _ = decide(NIKE, spec("Nike Men Court Legacy NN Sneakers", SHOES, brand="Nike", colour="White",
                                      gender="men"))
    assert failed == ["Model"]


def test_sneaker_colour_and_gender_must_match():
    ok, failed, _ = decide(NIKE, spec("Nike Men Court Vision Low Sneakers", SHOES, brand="Nike", colour="Black",
                                      gender="men"))
    assert failed == ["Colour"]
    ok, failed, _ = decide(NIKE, spec("Nike Women Court Vision Low Sneakers", SHOES, brand="Nike", colour="White",
                                      gender="women"))
    assert failed == ["Gender"]


def test_tshirt_neck_and_polo_rules():
    vneck = spec("U.S. Polo ASSN. Men's I638 V-Neck Embroidered Logo Lounge Cotton Regular Fit T-Shirt", TEE,
                 brand="U.S. POLO ASSN.", colour="White", gender="men", product_type="tshirt/v-neck")
    ok, failed, _ = decide(vneck, spec("U.S. Polo Assn. Men Round Neck Embroidered Logo Lounge T-Shirt", TEE,
                                       brand="U.S. Polo Assn.", colour="White", gender="men",
                                       product_type="tshirt/round-neck"))
    assert "Type" in failed


def test_generic_tshirt_needs_style_code():
    generic = spec("adidas Men Polyester Fitted T-Shirt", TEE, brand="adidas", colour="BLUBEA", gender="men",
                   product_type="tshirt", model_codes=["FJ9217"])
    ok, failed, _ = decide(generic, spec("ADIDAS Solid Men Round Neck Dark Blue T-Shirt", TEE, brand="ADIDAS",
                                         colour="Dark Blue", gender="men", product_type="tshirt/round-neck"))
    assert failed == ["Model"]  # brand + colour alone don't prove it's the same shirt


def test_part_number_leftovers_are_not_a_model_name():
    red_tape = spec("Red Tape Black Casual Shoes for Men", SHOES, brand="Red Tape", colour="White", gender="men",
                    model="Rsl1448a-10")
    ok, failed, _ = decide(red_tape, spec("RED TAPE Everyday Style Sneakers For Men", SHOES, brand="RED TAPE",
                                          colour="White", gender="men"))
    assert failed == ["Model"]  # "10" from the part number must not match any Red Tape shoe


def test_three_digit_numbers_are_models():
    nb = spec("New Balance Unisex-Adult 574 Sneaker", SHOES, brand="New Balance", colour="Black_2", gender="unisex")
    ok, _, _ = decide(nb, spec("New Balance 574 BLACK Men Casual Shoes", SHOES, brand="New Balance", colour="Black",
                               gender="men"))
    assert ok
    ok, failed, _ = decide(nb, spec("New Balance 5740 Sneakers For Men", SHOES, brand="New Balance", colour="Black",
                                    gender="men"))
    assert failed == ["Model"]


def test_suede_version_is_a_different_shoe():
    suede = spec("Nike Mens Court Vision Lo Suede Sneakers", SHOES, brand="Nike", colour="PHANTOM/CREAM II", gender="men")
    ok, failed, _ = decide(suede, spec("Nike Men Court Vision Low Sneakers", SHOES, brand="Nike", colour="White",
                                       gender="men"))
    assert failed == ["Model"]
    ok, _, _ = decide(suede, spec("Nike Court Vision Low Suede Men's Shoes", SHOES, brand="Nike", colour="Sail",
                                  gender="men"))
    assert ok


def test_sandals_and_formal_shoes_are_not_sneakers():
    bata = spec("Bata Men's Lace-up Sneaker", SHOES, brand="Bata", colour="Brown", gender="men", model="Lace-up Sneaker")
    for title, kind in (("Bata Men Brown Leather Comfort Sandals", "Sandals"),
                        ("Bata Mens Formal Derby Shoes - (Black) Casuals For Men", "shoe")):
        ok, failed, _ = decide(bata, spec(title, SHOES, brand="Bata", colour="Brown", gender="men", kind=kind))
        assert "Category" in failed


def test_solid_polo_is_not_striped_polo():
    arrow = spec("Arrow Sport Solid Polo T Shirt for Men", TEE, brand="Arrow", colour="Nude", gender="men",
                 product_type="polo")
    ok, failed, _ = decide(arrow, spec("Arrow Striped Sport Polo Collar T-shirt", TEE, brand="Arrow", colour="Beige",
                                       gender="men", product_type="polo"))
    assert "Pattern" in failed


def test_kids_shoe_is_not_the_adult_one():
    kids = spec("Nike Unisex Kids Court Borough Low Recraft (GS) Sneakers", SHOES, brand="Nike", colour="Black",
                gender="kids")
    ok, failed, _ = decide(kids, spec("NIKE court borough low prem Sneakers For Men", SHOES, brand="NIKE",
                                      colour="Black", gender="men"))
    assert not ok and "Gender" in failed


def test_extra_name_on_candidate_means_different_product():
    club = spec("Nike Mens Club Tee T Shirt", TEE, brand="Nike", colour="White", gender="men", product_type="tshirt")
    ok, failed, _ = decide(club, spec("Nike Jordan Flight Club Men's T-Shirt", TEE, brand="Nike", colour="White",
                                      gender="men", product_type="tshirt"))
    assert failed == ["Model"]


def test_different_season_kit_is_different_product():
    rm = spec("adidas Performance Real Madrid Home Jersey 2025/2026 White Men", TEE, brand="adidas", colour="White",
              gender="men", product_type="jersey")
    ok, failed, _ = decide(rm, spec("ADIDAS Men Real Madrid 26/27 Home Football Jersey", TEE, brand="ADIDAS",
                                    colour="White", gender="men", product_type="jersey"))
    assert "Season" in failed
    ok, _, _ = decide(rm, spec("ADIDAS Men Real Madrid 25/26 Home Football Jersey", TEE, brand="ADIDAS",
                               colour="White", gender="men", product_type="jersey"))
    assert ok


def test_sub_brand_and_jordan_aliases():
    jordan = spec("Jordan Nike Sneakers for Men", SHOES, brand="Jordan", colour="BLACK/WHITE-GYM RED", gender="men",
                  model="Air Jordan 1 Mid")
    ok, _, _ = decide(jordan, spec("Nike Air Jordan 1 Mid Shoes", SHOES, brand="Nike", colour="Black", gender="men"))
    assert ok
    arrow = spec("Arrow Sport Solid Polo T-Shirt for Men", TEE, brand="Arrow", colour="Blue", gender="men",
                 product_type="polo")
    result, _ = evaluate(arrow, spec("Arrow Sport Solid Men Polo Neck Blue T-Shirt", TEE, brand="Arrow Sport",
                                     colour="Blue", gender="men", product_type="polo"))
    model = next(c for c in result.checks if c.name == "Model")
    # "Sport" is part of Flipkart's brand name, not a missing model word; what's left is a generic
    # polo, which needs a style-code match
    assert "missing" not in (model.note or "") and "style-code" in model.note


def test_colour_and_size_after_the_shoe_name_are_not_model_words():
    samba = spec("adidas Samba OG Sneaker Oat/Wonder/White/Gum 10 UK (11US) (IG6170)", SHOES, brand="adidas",
                 colour="Oat/Wonder White/Gum", gender="men")
    ok, _, _ = decide(samba, spec("Adidas Original Men Samba OG Casual Shoes", SHOES, brand="ADIDAS", colour="Beige",
                                  gender="men"))
    assert ok


def test_model_number_at_end_of_platform_title_is_kept():
    jockey = spec("Jockey 2714 Men Super Combed Cotton Rich Round Neck Half Sleeve Regular Fit", TEE, brand="Jockey",
                  colour="Wine Tasting", gender="men", product_type="tshirt/round-neck")
    ok, _, _ = decide(jockey, spec("Jockey Combed Cotton Rich Round Neck Half Sleeve Tshirt-2714", TEE, brand="Jockey",
                                   colour="Red", gender="men", product_type="tshirt/round-neck"))
    assert ok


def test_generic_shape_words_are_not_a_model_name():
    broomi = spec("High-Top Sneakers with Spider Web Print, Lace-Up", SHOES, brand="BROOMI", colour="RED_BLACK",
                  gender="men", model="Broomi High-top")
    ok, failed, _ = decide(broomi, spec("BROOMI Broomi Graphic Print High Tops For Men", SHOES, brand="BROOMI",
                                        colour="Red", gender="men"))
    assert failed == ["Model"]  # "high top" is a shape, not a name: needs a style code
    campus = spec("Campus Men Og-22 Sneakers", SHOES, brand="Campus", colour="WHT/RED", gender="men")
    ok, _, _ = decide(campus, spec("CAMPUS OG-22 High Tops For Men", SHOES, brand="CAMPUS", colour="White",
                                   gender="men"))
    assert ok  # "OG-22" is a name even though it's short


def test_kids_size_words_and_fabrics_are_not_model_names():
    kid = spec("Puma Unisex Kid Racer PS V2 Sneaker", SHOES, brand="PUMA", colour="Black-ARUBA BLUE-Silver",
               gender="kids")
    ok, _, _ = decide(kid, spec("Puma Kids Racer V2 Sneakers", SHOES, brand="Puma", colour="Black", gender="kids"))
    assert ok
    polo = spec("Allen Solly Women's Polo Neck Synthetic T-Shirt | Soft Touch Fabric", TEE, brand="Allen Solly",
                colour="Lt Pink Solid", gender="women", product_type="polo")
    result, _ = evaluate(polo, spec("Allen Solly Woman Polo Collar Short Sleeves T-shirt", TEE, brand="Allen Solly",
                                    colour="Pink", gender="women", product_type="polo"))
    model = next(c for c in result.checks if c.name == "Model")
    assert "synthetic" not in (model.note or "")
