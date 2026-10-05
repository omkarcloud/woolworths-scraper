"""Live endpoint smoke tests: one call per /woolworths/* route against a
running service, with example values proven to return data (2026-10-05).
The listing tooling reads each route's FIRST call from this file's AST as
its working example, so the values stay literals.

Skipped unless WOOLWORTHS_BASE points at a running service:

    ONLY_SCRAPER=woolworths python run.py
    WOOLWORTHS_BASE=http://127.0.0.1:6002 python -m pytest woolworths/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("WOOLWORTHS_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set WOOLWORTHS_BASE to run live endpoint tests")


def call(path, status=200, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=180)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def test_search():
    page = call("/woolworths/products/search", query="milk")
    assert page["count"] > 500 and page["next"] and len(page["products"]) >= 36
    assert page["products"][0]["pricing"]["currency"] == "AUD"
    assert any(p["rating"] for p in page["products"])
    assert page["filters"]["brands"] and page["related_searches"]
    filtered = call("/woolworths/products/search", query="bread", sort="price_asc", brands="Woolworths",
                    dietary="vegan", category="bakery")
    assert 0 < filtered["count"] < page["count"]
    assert all(p["brand"] == "Woolworths" for p in filtered["products"])
    specials = call("/woolworths/products/search", query="chocolate", specials_only="true")
    assert any(p["pricing"]["is_on_special"] or p["promotion"] for p in specials["products"])
    assert call("/woolworths/products/search", query="milk", page=2)["current_page"] == 2
    assert call("/woolworths/products/autocomplete", query="choc")["suggestions"]


def test_product():
    product = call("/woolworths/products/details", product="888140")["product"]
    assert product["barcode"] == "9300633556150" and product["nutrition"]["nutrients"]
    assert product["ingredients"] and product["country_of_origin"]["country"] == "Australia"
    link = "https://www.woolworths.com.au/shop/productdetails/888140/woolworths-full-cream-milk"
    assert call("/woolworths/products/details", product=link)["product"]["id"] == 888140
    bulk = call("/woolworths/products/bulk", products="888140,263669")
    assert bulk["count"] == 2 and bulk["not_found"] == []
    assert call("/woolworths/products/barcode", barcode="9300633556150")["product"]["id"] == 888140
    assert call("/woolworths/products/nutrition", product="888140")["nutrition"]["serving_size"]


def test_reviews():
    page = call("/woolworths/products/reviews", product="365569")
    assert page["count"] > 100 and len(page["reviews"]) == 10 and page["rating"]["average"]
    low = call("/woolworths/products/reviews", product="365569", sort="lowest_rating", limit=5)
    assert low["reviews"][0]["rating"] <= 2
    assert call("/woolworths/products/reviews", product="365569", page=2)["reviews"]


def test_stock_and_new():
    stock = call("/woolworths/products/stock", product="888140", location="2000")
    assert stock["count"] > 0 and "is_in_stock" in stock["stores"][0]
    assert call("/woolworths/products/stock", product="888140", location="Bondi")["location"]["postcode"]
    new = call("/woolworths/products/new")
    assert new["count"] > 0 and new["products"]


def test_categories():
    tree = call("/woolworths/categories")
    assert tree["count"] > 15 and any(c["slug"] == "bakery" for c in tree["categories"])
    assert call("/woolworths/categories", category="bakery", depth=1)["category"]["children"]
    page = call("/woolworths/categories/products", category="bakery")
    assert page["count"] > 100 and page["products"] and page["category"]["id"] == "1_DEB537E"
    deep = call("/woolworths/categories/products", category="https://www.woolworths.com.au/shop/browse/bakery/packaged-bread-bakery",
                sort="unit_price_asc")
    assert deep["products"] and deep["category"]["level"] == 2
    assert call("/woolworths/categories/products", category="1_DEB537E", specials_only="true")["products"]


def test_specials():
    types = call("/woolworths/specials/types")["types"]
    assert any(t["type"] == "half_price" for t in types)
    page = call("/woolworths/specials", type="half_price")
    assert page["count"] > 50 and page["products"][0]["pricing"]["was_price"]
    assert call("/woolworths/specials", type="lower_shelf_price")["products"]


def test_stores():
    found = call("/woolworths/stores/search", location="2000")
    assert found["count"] == 10 and found["stores"][0]["trading_hours"]
    assert call("/woolworths/stores/search", location="Bondi Junction", division="all", limit=5)["stores"]
    assert call("/woolworths/stores/search", location="-37.8136,144.9631")["stores"][0]["address"]["state"] == "VIC"
    assert call("/woolworths/stores/details", store="8964")["store"]["name"] == "Barangaroo Metro"
    assert call("/woolworths/stores/pickup-locations", postcode="3000")["pickup_locations"]
    assert call("/woolworths/locations/search", query="bondi")["locations"][0]["postcode"] == "2026"


def test_errors():
    # paths via variables so the listing tooling never reads an error case
    # as a route's working example
    details, search, store = "/woolworths/products/details", "/woolworths/products/search", "/woolworths/stores/details"
    barcode, tree, specials = "/woolworths/products/barcode", "/woolworths/categories", "/woolworths/specials"
    call(details, status=404, product="99999999")
    call(details, status=400, product="https://www.coles.com.au/product/1")
    call(search, status=400)
    call(search, status=400, query="milk", sort="cheapest")
    call(search, status=400, query="bread", category="bakery/packaged-bread-bakery")
    call(barcode, status=404, barcode="1234567890123")
    call(tree, status=404, category="nope/nope")
    call(specials, status=400, type="nope")
    call(store, status=404, store="999999")
