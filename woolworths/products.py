"""/woolworths/products/* — search, details, bulk lookup, barcode lookup,
reviews, in-store stock, new arrivals, the nutrition panel and search
autocomplete, all from the storefront's own JSON API (fetch.py).

Listings are 36 per page: the upstream cap ("Page size should not be greater
than the limit: 36"). Every listing is enriched with ratings in one extra
GraphQL call, because the tiles themselves always carry a zeroed rating."""
from woolworths import parsers as P
from woolworths import refs
from woolworths import shared
from woolworths.fetch import WoolworthsNotFound, graphql, run_parallel, soft, ui, ui_post

PAGE_SIZE = 36

REVIEWS_QUERY = """query productDetailsPage($id: ID!, $order: ProductReviewSortType, $skip: Int, $take: Int) {
  product(id: $id) {
    rating { %s }
    reviews(skip: $skip, take: $take, order: $order) {
      items { body rating member source createdDate }
      pageInfo { hasNextPage }
      totalCount
    }
  }
}""" % shared.RATING_FIELDS

RATING_QUERY = "query ProductDetail($id: ID!) { product(id: $id) { rating { %s } } }" % shared.RATING_FIELDS


def build_filters(brands=None, allergens=None, dietary=None, health_star_ratings=None,
                  sellers=None, category_id=None):
    """Validated filter params -> the API's Filters list."""
    out = []
    for key, terms in (("Level1Categories", [category_id] if category_id else None), ("Brand", brands),
                       ("Allergens", allergens), ("Lifestyle", dietary),
                       ("Healthstar", health_star_ratings), ("Vendor", sellers)):
        if terms:
            out.append({"Key": key, "Items": [{"Term": term} for term in terms]})
    return out


def listing(tiles, total, page, aggregations=None):
    """Tiles + total -> the shared listing members (pagination, filters,
    products with ratings)."""
    ratings = shared.ratings(P.stockcodes(tiles))
    out = {"pagination": P.pagination(page, PAGE_SIZE, total)}
    if aggregations is not None:
        out["filters"] = P.filters(aggregations)
    out["products"] = P.products(tiles, ratings)
    return out


def _search_raw(term, page=1, sort="TraderRelevance", filters=None, specials_only=False, page_size=PAGE_SIZE):
    section = "specials" if specials_only else "products"
    return ui_post("/Search/products", {
        "SearchTerm": term,
        "PageNumber": page,
        "PageSize": page_size,
        "SortType": sort,
        "Filters": filters or [],
        "IsSpecial": bool(specials_only),
        "Location": f"/shop/search/{section}?searchTerm={term}",
    }) or {}


def _top_level_category(category):
    """The search `category` filter only takes a department (level 1)."""
    if not category:
        return None
    node, _ = shared.category_node(category)
    if P.to_int(node.get("NodeLevel")) != 1 or node.get("IsSpecial"):
        raise ValueError("category must be a top-level department here (bakery, drinks, ...) — "
                         "use /woolworths/categories/products to list a deeper category")
    return P.text(node.get("NodeId"))


def search(query, page=1, sort="TraderRelevance", category=None, brands=None, allergens=None,
           dietary=None, health_star_ratings=None, sellers=None, specials_only=None):
    filters = build_filters(brands, allergens, dietary, health_star_ratings, sellers,
                            _top_level_category(category))
    body = _search_raw(query, page, sort, filters, bool(specials_only))
    tiles = P.bundle_tiles(body.get("Products"))
    out = {
        "query": query,
        "suggested_query": P.text(body.get("SuggestedTerm")),
        "related_searches": [t for t in (P.text(x) for x in body.get("FacetFilters") or []) if t],
    }
    out.update(listing(tiles, body.get("SearchResultsCount"), page, body.get("Aggregations") or []))
    return out


def _detail_raw(product):
    detail = ui(f"/product/detail/{product}") or {}
    if not P.is_real_product(detail.get("Product")):
        raise WoolworthsNotFound(f"product '{product}' not found")
    return detail


def _rating(product):
    data = soft(lambda: graphql(RATING_QUERY, {"id": product}), default=None)() or {}
    return P.rating((data.get("product") or {}).get("rating"))


def details(product):
    detail, rating = run_parallel([lambda: _detail_raw(product), lambda: _rating(product)])
    return {"product": P.product_details(detail, rating)}


def nutrition(product):
    """The nutrition panel alone, with the ingredient list and dietary
    claims — the slim cut of details for diet and health apps."""
    detail = _detail_raw(product)
    full = P.product_details(detail)
    return {
        "product": {key: full.get(key) for key in ("id", "name", "link", "barcode", "brand", "package_size", "image")},
        "ingredients": full.get("ingredients"),
        "dietary": full.get("dietary"),
        "nutrition": full.get("nutrition"),
    }


def bulk(products):
    """Up to 20 products by stockcode in one upstream call. Unknown
    stockcodes are reported under `not_found`."""
    rows, ratings = run_parallel([lambda: ui("/products/" + ",".join(products)) or [],
                                  lambda: shared.ratings(products)])
    found = P.products(rows if isinstance(rows, list) else [], ratings)
    found_ids = {str(p["id"]) for p in found}
    return {
        "count": len(found),
        "not_found": [P.to_int(code) for code in products if code not in found_ids],
        "products": found,
    }


def barcode(barcode):
    """The site's search matches a barcode exactly; the row whose own
    barcode equals the input is the product."""
    body = _search_raw(barcode, page_size=12)
    tiles = [t for t in P.bundle_tiles(body.get("Products")) if P.text(t.get("Barcode")) == barcode]
    if not tiles:
        raise WoolworthsNotFound(f"no Woolworths product has barcode {barcode}")
    ratings = shared.ratings(P.stockcodes(tiles[:1]))
    return {"barcode": barcode, "product": P.products(tiles[:1], ratings)[0]}


def reviews(product, sort="LATEST", page=1, limit=10):
    data = graphql(REVIEWS_QUERY, {"id": product, "order": sort, "skip": (page - 1) * limit, "take": limit})
    node = data.get("product")
    if not isinstance(node, dict):
        # The reviews service has no record: either the product has never
        # been rated or the stockcode does not exist. Tell them apart.
        _detail_raw(product)
        node = {}
    block = node.get("reviews") if isinstance(node.get("reviews"), dict) else {}
    rows = [P.review(r) for r in block.get("items") or [] if isinstance(r, dict)]
    return {
        "product_id": P.to_int(product),
        "product_link": refs.product_link(product),
        "rating": P.rating(node.get("rating")),
        "pagination": P.pagination(page, limit, block.get("totalCount")),
        "reviews": rows,
    }


def stock(product, location, in_stock_only=None, limit=10):
    """Which nearby stores have the product on the shelf."""
    where, place = shared.locate(location)
    params = {"IncludeInStockStoreOnly": "true" if in_stock_only else "false", "Max": limit}
    if "postcode" in where:
        params["Postcode"] = where["postcode"]
    else:
        params["Latitude"], params["Longitude"] = where["latitude"], where["longitude"]
    rows = ui(f"/product/{product}/Stores", params) or []
    stores = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and isinstance(row.get("Store"), dict):
            stores.append({"is_in_stock": P.bool_or_none(row.get("InstoreIsAvailable")),
                           "store": P.store(row["Store"])})
    return {
        "product_id": P.to_int(product),
        "product_link": refs.product_link(product),
        "location": place,
        "count": len(stores),
        "in_stock_count": sum(1 for s in stores if s["is_in_stock"]),
        "stores": stores,
    }


def new(page=1, sort="AvailableDateDesc", brands=None, allergens=None, dietary=None,
        health_star_ratings=None):
    """The site's "New" shelf: products added to the range recently."""
    body = ui_post("/Products/New", {
        "pageNumber": page, "pageSize": PAGE_SIZE, "sortType": sort,
        "filters": build_filters(brands, allergens, dietary, health_star_ratings),
    }) or {}
    tiles = [t for t in body.get("Items") or [] if isinstance(t, dict)]
    return listing(tiles, body.get("TotalRecordCount"), page, body.get("Aggregations") or [])


def autocomplete(query):
    body = ui("/search-suggestions/suggestionsb2c", {"searchTerm": query}) or {}
    suggestions = [s for s in (P.text(x) for x in body.get("suggestions") or []) if s]
    return {
        "query": query,
        "corrected_query": P.text(body.get("autoCorrectedTerm")),
        "count": len(suggestions),
        "suggestions": [{"text": s, "link": refs.search_link(s)} for s in suggestions],
    }
