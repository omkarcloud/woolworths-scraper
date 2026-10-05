"""Offline tests: ref parsing, the request schemas and the normalizers
against raw woolworths.com.au responses captured 2026-10-05
(woolworths/fixtures/*.json).

    python -m pytest woolworths/test_parsers.py -q
"""
import json
import os

import pytest

from schema_fields import load_query
from woolworths import parsers as P
from woolworths import refs
from woolworths import schemas as S
from woolworths import shared

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def fx(name):
    with open(os.path.join(FIX, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def _no_camel_or_url_keys(obj, path="$"):
    """Every emitted key is snake_case and no key is named *url*."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key == key.lower() and " " not in key, f"{path}.{key} not snake_case"
            assert "url" not in key, f"{path}.{key} should be a *link"
            _no_camel_or_url_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _no_camel_or_url_keys(value, f"{path}[{i}]")


def _no_empty_strings(obj, path="$"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            _no_empty_strings(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _no_empty_strings(value, f"{path}[{i}]")
    else:
        assert obj != "", f"{path} is an empty string (must be null)"


# ---- refs -----------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("888140", "888140"), (" 0888140 ", "888140"),
    ("https://www.woolworths.com.au/shop/productdetails/888140/woolworths-full-cream-milk", "888140"),
    ("woolworths.com.au/shop/productdetails/263669", "263669"),
    ("https://www.woolworths.com.au/shop/productdetails/1100355776/x?googleshop=true", "1100355776"),
])
def test_resolve_product(value, expected):
    assert refs.resolve_product(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "https://www.coles.com.au/product/1",
                                   "https://www.woolworths.com.au/shop/browse/bakery"])
def test_resolve_product_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_product(value)


def test_resolve_products():
    assert refs.resolve_products("888140, https://www.woolworths.com.au/shop/productdetails/263669/x,888140") == [
        "888140", "263669"]
    with pytest.raises(ValueError):
        refs.resolve_products(",".join(str(n) for n in range(1, 23)))


@pytest.mark.parametrize("value, expected", [
    ("1_DEB537E", {"id": "1_DEB537E"}),
    ("1-E5BEE36E", {"id": "1-E5BEE36E"}),
    ("specialsgroup.3676", {"id": "specialsgroup.3676"}),
    ("bakery", {"path": ["bakery"]}),
    ("Bakery/Packaged-Bread-Bakery/", {"path": ["bakery", "packaged-bread-bakery"]}),
    ("https://www.woolworths.com.au/shop/browse/specials/half-price?pageNumber=2", {"path": ["specials", "half-price"]}),
])
def test_resolve_category(value, expected):
    assert refs.resolve_category(value) == expected


@pytest.mark.parametrize("value", ["", "bak ery", "https://www.woolworths.com.au/shop/productdetails/1/x",
                                   "https://example.com/shop/browse/bakery"])
def test_resolve_category_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_category(value)


def test_resolve_store_and_barcode():
    assert refs.resolve_store("8964") == "8964"
    assert refs.resolve_store(
        "https://www.woolworths.com.au/shop/storelocator/nsw-barangaroo-barangaroo-metro-8964") == "8964"
    assert refs.resolve_barcode("9300 6335-56150") == "9300633556150"
    for bad in ("abc", "1234567"):
        with pytest.raises(ValueError):
            refs.resolve_barcode(bad)


@pytest.mark.parametrize("value, expected", [
    ("2000", {"postcode": "2000"}),
    ("-33.8688, 151.2093", {"latitude": -33.8688, "longitude": 151.2093}),
    ("Bondi  Junction", {"suburb": "Bondi Junction"}),
])
def test_resolve_location(value, expected):
    assert refs.resolve_location(value) == expected


@pytest.mark.parametrize("value", ["", "20", "123456", "95,200", "ab"])
def test_resolve_location_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_location(value)


# ---- schemas --------------------------------------------------------------------------

def test_search_schema_maps_values():
    data, error = load_query(S.SearchSchema, {
        "query": " oat  milk ", "sort": "PRICE_ASC", "brands": "Vitasoy, Oatly",
        "allergens": "gluten_free,Dairy_Free", "dietary": "vegan", "health_star_ratings": "4.5,5",
        "specials_only": "true", "category": "drinks"})
    assert error is None
    assert data["query"] == "oat milk" and data["sort"] == "PriceAsc" and data["page"] == 1
    assert data["brands"] == ["Vitasoy", "Oatly"]
    assert data["allergens"] == ["Gluten Free", "Dairy Free"] and data["dietary"] == ["Vegan"]
    assert data["health_star_ratings"] == ["4.5", "5"] and data["specials_only"] is True
    assert data["category"] == {"path": ["drinks"]}


def test_schema_rejections():
    for schema, query in [
        (S.SearchSchema, {}),
        (S.SearchSchema, {"query": "milk", "sort": "cheapest"}),
        (S.SearchSchema, {"query": "milk", "allergens": "kryptonite_free"}),
        (S.SearchSchema, {"query": "milk", "product_id": "1"}),
        (S.ReviewsSchema, {"product": "888140", "limit": "51"}),
        (S.StockSchema, {"product": "888140"}),
        (S.StoreSchema, {"store": "8964", "division": "all"}),
        (S.PickupLocationsSchema, {"postcode": "200"}),
        (S.CategoryTreeSchema, {"depth": "6"}),
    ]:
        data, error = load_query(schema, query)
        assert data is None and error["error"].startswith("Invalid parameters"), (schema, query)


def test_schema_defaults():
    data, _ = load_query(S.ReviewsSchema, {"product": "888140"})
    assert data == {"product": "888140", "sort": "LATEST", "page": 1, "limit": 10}
    data, _ = load_query(S.SpecialsSchema, {"type": "Buy-More Save More"})
    assert data["type"] == "buy_more_save_more" and data["sort"] == "TraderRelevance"
    data, _ = load_query(S.StoreSearchSchema, {"location": "2000", "division": "ALL"})
    assert data["division"] == "SUPERMARKETS,PETROL,BWS" and data["limit"] == 10
    data, _ = load_query(S.NewProductsSchema, {})
    assert data["sort"] == "AvailableDateDesc"


# ---- value helpers ----------------------------------------------------------------------

def test_value_helpers():
    assert P.iso_datetime("2026-10-08T20:55:51.3214870+11:00") == "2026-10-08T09:55:51Z"
    assert P.iso_datetime("2026-09-15T13:49:00.000Z") == "2026-09-15T13:49:00Z"
    assert P.iso_datetime("0001-01-01T00:00:00") is None and P.iso_datetime("junk") is None
    assert P.iso_date("2026-10-07T00:00:00.0000000Z") == "2026-10-07"
    assert P.utc_offset("11:0") == "+11:00" and P.utc_offset("9:30") == "+09:30"
    assert P.quantity("730.0kJ") == {"amount": 730.0, "unit": "kJ", "qualifier": None}
    assert P.quantity("< 1.0g") == {"amount": 1.0, "unit": "g", "qualifier": "<"}
    assert P.quantity(None) is None
    assert P.clean_html("<p>A &amp; B</p><ul><li>one</li><li>two</li></ul>") == "A & B\n- one\n- two"
    assert P.clean_html("  ") is None
    assert P.split_list("Dairy Free, Egg Free,Dairy Free") == ["Dairy Free", "Egg Free"]
    assert P.flag("True") is True and P.flag("False") is False and P.flag(None) is None
    assert P.pagination(2, 36, 593) == {"page": 2, "items_per_page": 36, "total_pages": 17, "total_count": 593}


# ---- products ---------------------------------------------------------------------------

def test_search_products():
    body = fx("search")
    tiles = P.bundle_tiles(body["Products"])
    ratings = P.ratings_by_id(fx("ratings")["data"])
    rows = P.products(tiles, ratings)
    assert len(rows) == len(tiles) > 0
    first = rows[0]
    assert first["id"] == 263669 and first["barcode"] == "9310023138705" and first["brand"] == "Wonder"
    assert first["link"] == ("https://www.woolworths.com.au/shop/productdetails/263669/"
                             "wonder-white-bread-vitamins-minerals-sandwich")
    assert first["pricing"] == {
        "price": 4.6, "currency": "AUD", "was_price": None, "savings_amount": None,
        "unit_price": 0.66, "unit_price_measure": "100G", "is_on_special": False,
        "is_half_price": False, "is_member_special": False, "sold_by": "Each",
        "minimum_quantity": 1.0, "weight_range_price": None}
    assert first["promotion"]["type"] == "LowPrice" and first["promotion"]["label"] == "EVERYDAY LOW PRICE"
    assert first["is_sponsored"] is True and first["seller"] is None
    assert first["dietary"]["health_star_rating"] == 4.5 and "Sesame" in first["dietary"]["may_contain"]
    assert first["categories"]["primary_department"] == {"id": "1_DEB537E", "name": "Bakery"}
    assert first["availability"]["supply_limit"] == 36
    for row in rows:
        _no_camel_or_url_keys(row)
        _no_empty_strings(row)
        assert row["pricing"]["currency"] == "AUD"
    facets = P.filters(body["Aggregations"])
    assert facets["categories"][0]["id"].startswith("1_") and facets["brands"] and facets["allergens"]
    assert all(isinstance(r["value"], float) for r in facets["health_star_ratings"])


def test_specials_promotions():
    rows = P.products(P.bundle_tiles(fx("search_specials")["Products"]))
    special = next(r for r in rows if r["pricing"]["is_on_special"])
    assert special["pricing"]["was_price"] > special["pricing"]["price"]
    assert special["pricing"]["savings_amount"] == round(
        special["pricing"]["was_price"] - special["pricing"]["price"], 2)
    assert special["promotion"]["type"] == "Special" and special["promotion"]["label"].startswith("Save $")
    assert special["promotion"]["badge_image"].startswith("https://")
    multibuy = next(r for r in rows if r["promotion"] and r["promotion"]["multibuy"])
    assert multibuy["promotion"]["multibuy"]["quantity"] == 2
    assert multibuy["promotion"]["multibuy"]["price"] in (10.0, 12.0)
    assert multibuy["promotion"]["offer_group_id"].isdigit()
    assert "<" not in multibuy["promotion"]["offer_text"]


def test_browse_and_new_products():
    browse = P.products(P.bundle_tiles(fx("browse_category")["Bundles"]))
    new = P.products(fx("new_products")["Items"])
    assert browse and new
    for row in browse + new:
        assert row["id"] and row["name"] and row["link"].startswith("https://www.woolworths.com.au/shop/productdetails/")
        _no_camel_or_url_keys(row)


def test_bulk_skips_unknown_stockcodes():
    rows = P.products(fx("products_bulk"))
    assert [r["id"] for r in rows] == [263669, 888140]


def test_product_details():
    out = P.product_details(fx("detail_basic"), P.rating({"average": 1.0, "ratingCount": 1, "reviewCount": 1,
                                                         "oneStarCount": 1}))
    assert out["id"] == 263669 and out["rating"]["distribution"]["1"] == 1
    assert out["ingredients"].startswith("Wheat Flour") and out["description"].startswith("Wonder-fully soft")
    assert out["country_of_origin"]["country"] == "Australia"
    assert out["country_of_origin"]["local_ingredient_percentage"] == 85.0
    assert out["storage_instructions"] and out["primary_category"] == {
        "department": "bakery", "aisle": "white & wholemeal bread"}
    assert len(out["images"]) == 9 and out["variants"] is None and out["delivery"] is None
    nutrition = out["nutrition"]
    assert nutrition["serving_size"] == "74.0 G" and nutrition["servings_per_pack"] == 9.5
    by_name = {n["name"]: n for n in nutrition["nutrients"]}
    assert by_name["Energy"]["per_100"] == {"amount": 990.0, "unit": "kJ", "qualifier": None}
    assert by_name["Saturated"]["is_sub_nutrient"] is True and by_name["Saturated"]["per_serving"]["qualifier"] == "<"
    assert by_name["Potassium"]["per_serving"]["unit"] == "mg"      # only in the attribute table
    assert len(by_name) == len(nutrition["nutrients"])              # the two sources did not duplicate
    _no_camel_or_url_keys(out)
    _no_empty_strings(out)


def test_product_details_special():
    out = P.product_details(fx("detail_special"))
    assert out["pricing"]["is_on_special"] is True and out["pricing"]["was_price"] == 8.0
    assert out["pricing"]["savings_amount"] == 3.2 and out["promotion"]["badge"] == "40% Off"
    assert out["availability"]["next_availability_date"] == "2026-10-07"


def test_product_details_marketplace():
    out = P.product_details(fx("detail_variant"))
    assert out["is_marketplace_item"] is True
    assert out["seller"] == {"id": "Q29tcGFueS00NDQxMA==", "name": "Boutique Retailer",
                             "is_free_shipping": True, "dispatch_note": "1-2 business days"}
    assert out["variants"]["options"] == [
        {"name": "Colour", "value": "Pink (Salmon)", "values": ["Pink (Salmon)", "Yellow"]},
        {"name": "Size", "value": "S", "values": ["L", "M", "S", "XL"]}]
    assert 1100355772 in out["variants"]["product_ids"]
    assert out["delivery"]["flat_fee"] == 10.0 and out["delivery"]["estimated_from"].endswith("Z")
    assert out["delivery"]["is_change_of_mind_returnable"] is False
    assert "<" not in out["description"] and out["nutrition"] is None
    market = P.product_details(fx("detail_market"))
    assert market["seller"]["name"] == "KG Superstore" and market["pricing"]["price"] == 600.3
    _no_camel_or_url_keys(out)


def test_unknown_product_is_a_shell():
    assert P.is_real_product(fx("detail_notfound")["Product"]) is False
    assert P.is_real_product(fx("detail_basic")["Product"]) is True
    assert P.is_real_product(None) is False


def test_partial_payloads_never_crash():
    assert P.product({})["id"] is None and P.product({})["pricing"]["price"] is None
    assert P.product_details({})["nutrition"] is None
    assert P.products([None, {}, "x"]) == []
    assert P.bundle_tiles([None, {"Products": None}, {"Products": [None, {"Stockcode": 1}]}]) == [{"Stockcode": 1}]
    assert P.filters(None) == {"categories": [], "brands": [], "allergens": [], "dietary": [],
                               "health_star_ratings": [], "sellers": []}
    assert P.store({})["address"]["latitude"] is None and P.trading_hours(None) == []
    assert P.rating(None) is None and P.rating({"ratingCount": 0}) is None
    assert P.review({})["text"] is None and P.pickup_location({})["id"] is None


# ---- ratings / reviews ------------------------------------------------------------------

def test_ratings_and_reviews():
    ratings = P.ratings_by_id(fx("ratings")["data"])
    assert ratings["888140"] == {"average": 2.67, "ratings_count": 6, "reviews_count": 6,
                                 "distribution": {"5": 2, "4": 0, "3": 1, "2": 0, "1": 3}}
    block = fx("reviews")["data"]["product"]["reviews"]
    rows = [P.review(r) for r in block["items"]]
    assert rows[0] == {"rating": 5, "author": "cannycarl", "source": "Bunch",
                       "created_at": "2026-09-15T13:49:00Z",
                       "text": "Best milk. Great fresh flavour well presented good price nice in my coffee and cereal"}
    assert P.pagination(1, 5, block["totalCount"])["total_pages"] == 173


# ---- categories -------------------------------------------------------------------------

def test_category_tree_and_lookup():
    roots = fx("categories")["Categories"]
    index = shared._index(roots)
    node, slugs = index["by_id"]["specialsgroup.3676"]
    assert slugs == ["specials", "half-price"] and node["IsSpecial"] is True
    assert ("specials", "half-price") in index["by_path"]
    department = roots[1]
    out = P.category(department, [department["UrlFriendlyName"]], depth=1)
    assert out["level"] == 1 and out["link"].startswith("https://www.woolworths.com.au/shop/browse/")
    assert out["children"] and all(c["children"] == [] for c in out["children"])
    assert out["children"][0]["link"].startswith(out["link"] + "/")
    full = P.category(department, [department["UrlFriendlyName"]])
    assert any(c["children"] for c in full["children"])
    _no_camel_or_url_keys(full)


# ---- stores -----------------------------------------------------------------------------

def test_stores():
    rows = [P.store(s) for s in fx("stores")["Stores"]]
    first = rows[0]
    assert first["id"] == "8964" and first["division"] == "supermarkets" and first["distance_km"] == 0.45
    assert first["address"]["postcode"] == "2000" and isinstance(first["address"]["latitude"], float)
    assert first["utc_offset"] == "+11:00" and len(first["trading_hours"]) == 8
    today = first["trading_hours"][0]
    assert today["is_today"] is True and today["day"] in P._DAYS.values()
    assert len(today["opens_at"]) == 5 and today["opens_at"][2] == ":" and today["is_closed"] is False
    detail = P.store(fx("store"), include_partners=True)
    assert detail["distance_km"] is None and detail["nearby_partners"]
    assert "?" not in detail["nearby_partners"][0]["link"]          # tracking params dropped
    _no_camel_or_url_keys(detail)
    _no_empty_strings(detail)


def test_stock_suburbs_pickup():
    stock = fx("product_stores")
    assert all(isinstance(r["InstoreIsAvailable"], bool) for r in stock)
    assert P.store(stock[0]["Store"])["name"]
    place = P.suburb(fx("suburbs")["Suburbs"][0])
    assert place == {"name": "Bondi", "state": "NSW", "postcode": "2026", "label": "Bondi, NSW, 2026",
                     "latitude": -33.893, "longitude": 151.2634}
    point = P.pickup_location(fx("pickup_locations")[0])
    assert point["id"] == 11524222 and point["store_id"] == "1449" and point["fulfilment_method"] == "DriveUp"
    assert point["address"]["postcode"] == "2009"
