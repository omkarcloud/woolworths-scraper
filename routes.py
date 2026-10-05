"""The 17 Woolworths endpoints. Every path is served with and without the
`/woolworths` prefix, so code generated against the hosted API on RapidAPI
(paths like /products/details) runs unchanged against this server.

Params are validated by the marshmallow schemas in woolworths/schemas.py
(unknown params are rejected). Errors: bad params -> 400, product / category
/ store not on woolworths.com.au -> 404, retries exhausted / blocked -> 500.
"""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from woolworths import categories, products, schemas, stores
from scraper_errors import BadRequest, NotFound
from schema_fields import load_query


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "crème fraîche" would arrive mangled)."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _page_link(path, params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "")}
    query["page"] = page
    host = request.get_header("Host") or "localhost"
    return f"{request.urlparts.scheme}://{host}{path}?{urlencode(query)}"


def paginate(result, path, params):
    """Lift the `pagination` block into flat count / per_page / current_page /
    total_pages / next / previous fields (the hosted API's shape)."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)
    page = int(pagination.get("page") or 1)
    total_pages = int(pagination.get("total_pages") or 0)
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(path, params, page + 1 if page < total_pages else None),
        "previous": _page_link(path, params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def handle(label, schema, impl, paginated=False):
    raw = query_dict()
    data, error = load_query(schema, raw)
    if error:
        return json_response(error, 400)
    try:
        result = impl(**data)
    except ValueError as e:                # params valid but not usable (unknown specials type)
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"woolworths rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:                 # retries exhausted / blocked
        return json_response({"error": f"woolworths {label} failed: {e}"}, 500)
    if paginated:
        result = paginate(result, request.path, raw)
    return json_response(result)


def mount(path, schema, impl, paginated=False):
    """Serve an endpoint at /path and /woolworths/path."""
    def handler():
        return handle(path.strip("/"), schema, impl, paginated)
    handler.__name__ = "woolworths_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/woolworths" + path, method="GET")(handler)


ENDPOINTS = [
    ("/products/details", schemas.ProductSchema, products.details, False),
    ("/products/search", schemas.SearchSchema, products.search, True),
    ("/products/autocomplete", schemas.AutocompleteSchema, products.autocomplete, False),
    ("/products/barcode", schemas.BarcodeSchema, products.barcode, False),
    ("/products/bulk", schemas.ProductsSchema, products.bulk, False),
    ("/products/nutrition", schemas.ProductSchema, products.nutrition, False),
    ("/products/reviews", schemas.ReviewsSchema, products.reviews, True),
    ("/products/stock", schemas.StockSchema, products.stock, False),
    ("/products/new", schemas.NewProductsSchema, products.new, True),
    ("/specials", schemas.SpecialsSchema, categories.specials, True),
    ("/specials/types", schemas.EmptySchema, categories.specials_types, False),
    ("/categories", schemas.CategoryTreeSchema, categories.tree, False),
    ("/categories/products", schemas.CategoryProductsSchema, categories.products, True),
    ("/stores/search", schemas.StoreSearchSchema, stores.search, False),
    ("/stores/details", schemas.StoreSchema, stores.details, False),
    ("/stores/pickup-locations", schemas.PickupLocationsSchema, stores.pickup_locations, False),
    ("/locations/search", schemas.LocationSearchSchema, stores.locations, False),
]

for _path, _schema, _impl, _paginated in ENDPOINTS:
    mount(_path, _schema, _impl, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
