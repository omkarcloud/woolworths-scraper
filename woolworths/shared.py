"""Lookups shared by the /woolworths/* endpoint modules: the category tree
(memoised in-process — an ~850 KB document that changes a few times a week),
category resolution against it, bulk ratings from the GraphQL endpoint and
suburb -> coordinates for the store locator."""
import threading
import time

from woolworths import parsers as P
from woolworths.fetch import WoolworthsNotFound, graphql, soft, ui

TREE_TTL = 6 * 3600
SPECIALS_ROOT = "specialsgroup"

RATING_FIELDS = ("average reviewCount ratingCount oneStarCount twoStarCount "
                 "threeStarCount fourStarCount fiveStarCount")
RATINGS_QUERY = "query productTile($ids: [ID!]!) { products(ids: $ids) { id rating { %s } } }" % RATING_FIELDS

_lock = threading.Lock()
_memo = {}


def memo(key, ttl, build):
    now = time.time()
    with _lock:
        hit = _memo.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = build()
    with _lock:
        _memo[key] = (now + ttl, value)
    return value


# ---- ratings ------------------------------------------------------------------

def ratings(stockcodes):
    """{stockcode str: rating} for a page of products. Never fails the
    endpoint: a listing without ratings is still a listing."""
    codes = [str(c) for c in stockcodes if c is not None]
    if not codes:
        return {}
    data = soft(lambda: graphql(RATINGS_QUERY, {"ids": codes}), default=None)()
    return P.ratings_by_id(data)


# ---- category tree --------------------------------------------------------------

def _index(roots):
    """-> {"by_id": {node id lower: (node, slugs)}, "by_path": {slug tuple:
    (node, slugs)}}. The first node seen wins a duplicated slug path."""
    by_id, by_path = {}, {}

    def walk(node, slugs):
        node_id = P.text(node.get("NodeId"))
        entry = (node, slugs)
        if node_id:
            by_id.setdefault(node_id.lower(), entry)
        by_path.setdefault(tuple(slugs), entry)
        for child in node.get("Children") or []:
            if isinstance(child, dict):
                slug = P.text(child.get("UrlFriendlyName"))
                walk(child, slugs + [slug or ""])

    for root in roots:
        if isinstance(root, dict):
            walk(root, [P.text(root.get("UrlFriendlyName")) or ""])
    return {"by_id": by_id, "by_path": by_path}


def category_tree():
    """{"roots": [raw department nodes], "by_id": ..., "by_path": ...}."""
    def build():
        body = ui("/PiesCategoriesWithSpecials") or {}
        roots = [n for n in body.get("Categories") or [] if isinstance(n, dict)]
        if not roots:
            raise WoolworthsNotFound("category tree is empty")
        return dict(_index(roots), roots=roots)
    return memo("category_tree", TREE_TTL, build)


def category_node(ref):
    """A resolved category ref ({"id"} or {"path"}) -> (raw node, slug
    path). Raises WoolworthsNotFound with a usable hint."""
    tree = category_tree()
    if ref.get("id"):
        hit = tree["by_id"].get(ref["id"].lower())
        if hit:
            return hit
        raise WoolworthsNotFound(f"category '{ref['id']}' not found (see /woolworths/categories for ids)")
    path = tuple(ref.get("path") or [])
    hit = tree["by_path"].get(path)
    if hit:
        return hit
    raise WoolworthsNotFound(f"category '{'/'.join(path)}' not found (see /woolworths/categories for slugs)")


# ---- locations ------------------------------------------------------------------

def suburbs(query):
    body = ui("/StoreLocator/Suburbs", {"SearchTerm": query}) or {}
    return [P.suburb(s) for s in body.get("Suburbs") or [] if isinstance(s, dict)]


def locate(location):
    """A resolved location ({"postcode"} | {"latitude", "longitude"} |
    {"suburb"}) -> (store-locator query params, the place searched from).
    The place always has the suburb shape; a postcode / coordinate search
    fills only what was given."""
    place = {"name": None, "state": None, "postcode": None, "label": None,
             "latitude": None, "longitude": None}
    if "postcode" in location:
        place["postcode"] = location["postcode"]
        return {"postcode": location["postcode"]}, place
    if "latitude" in location:
        place["latitude"], place["longitude"] = location["latitude"], location["longitude"]
        return {"latitude": location["latitude"], "longitude": location["longitude"]}, place
    matches = suburbs(location["suburb"])
    if not matches:
        raise WoolworthsNotFound(f"no Australian suburb matches '{location['suburb']}'")
    wanted = location["suburb"].lower()
    place = next((m for m in matches if (m.get("name") or "").lower() == wanted), matches[0])
    return {"latitude": place["latitude"], "longitude": place["longitude"]}, place
