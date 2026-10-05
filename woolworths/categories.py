"""/woolworths/categories*, /woolworths/specials* — the category tree
(~2,700 nodes, five levels: department > category > subcategory > ...), the
products in any node, and the specials shelves (Half Price, Lower Shelf
Price, ...), which the site models as nodes of the same tree under
`specialsgroup`."""
import json

from woolworths import parsers as P
from woolworths import products as products_mod
from woolworths import shared
from woolworths.fetch import ui_post


def tree(category=None, depth=2):
    """The whole tree from the departments down, or one node's subtree.
    `depth` is how many levels below the starting point are expanded."""
    data = shared.category_tree()
    if category:
        node, slugs = shared.category_node(category)
        return {"depth": depth, "category": P.category(node, slugs, depth)}
    rows = [P.category(root, [P.text(root.get("UrlFriendlyName"))], depth - 1) for root in data["roots"]]
    return {"depth": depth, "count": len(rows), "categories": rows}


def _browse(node, slugs, page, sort, filters, specials_only):
    path = "/shop/browse/" + "/".join(s for s in slugs if s)
    is_special = bool(specials_only) or bool(node.get("IsSpecial"))
    if is_special and sort == "AvailableDateDesc":
        sort = "AvailableDateAsc"       # the specials shelves' own "New" order
    return ui_post("/browse/category", {
        "categoryId": P.text(node.get("NodeId")),
        "pageNumber": page,
        "pageSize": products_mod.PAGE_SIZE,
        "sortType": sort,
        "url": path,
        "location": path,
        "formatObject": json.dumps({"name": P.text(node.get("Description")) or ""}),
        "isSpecial": is_special,
        "isBundle": bool(node.get("IsBundle")),
        "isMobile": False,
        "filters": filters,
        "token": "",
        "gpBoost": 0,
        "isHideUnavailableProducts": False,
        "isRegisteredRewardCardPromotion": False,
        "enableAdReRanking": False,
        "groupEdmVariants": True,
        "categoryVersion": "v2",
    }) or {}


def _listing(node, slugs, page, sort, filters, specials_only):
    body = _browse(node, slugs, page, sort, filters, specials_only)
    tiles = P.bundle_tiles(body.get("Bundles"))
    out = {"category": P.category_ref(node, slugs)}
    out.update(products_mod.listing(tiles, body.get("TotalRecordCount"), page, body.get("Aggregations") or []))
    return out


def products(category, page=1, sort="TraderRelevance", brands=None, allergens=None, dietary=None,
             health_star_ratings=None, specials_only=None):
    node, slugs = shared.category_node(category)
    filters = products_mod.build_filters(brands, allergens, dietary, health_star_ratings)
    return _listing(node, slugs, page, sort, filters, specials_only)


# ---- specials ---------------------------------------------------------------------

def _specials_root():
    data = shared.category_tree()
    hit = data["by_id"].get(shared.SPECIALS_ROOT)
    return hit if hit else (None, [])


def specials_types():
    """The specials shelves the site currently runs (they change with the
    weekly catalogue), each with the `type` value /woolworths/specials takes."""
    root, slugs = _specials_root()
    rows = []
    for child in (root or {}).get("Children") or []:
        if not isinstance(child, dict):
            continue
        slug = P.text(child.get("UrlFriendlyName"))
        if not slug or slug.startswith("my-"):      # "My Specials and Offers" is login-only
            continue
        ref = P.category_ref(child, slugs + [slug])
        rows.append({"type": slug.replace("-", "_"), "id": ref["id"], "name": ref["name"], "link": ref["link"]})
    return {"count": len(rows), "types": rows}


def specials(type="half_price", page=1, sort="TraderRelevance", brands=None, allergens=None,
             dietary=None, health_star_ratings=None):
    root, slugs = _specials_root()
    wanted = type.replace("_", "-")
    node = next((c for c in (root or {}).get("Children") or []
                 if isinstance(c, dict) and P.text(c.get("UrlFriendlyName")) == wanted), None)
    if node is None:
        available = ", ".join(t["type"] for t in specials_types()["types"])
        raise ValueError(f"specials type '{type}' is not running right now — one of: {available}")
    filters = products_mod.build_filters(brands, allergens, dietary, health_star_ratings)
    out = {"type": type}
    out.update(_listing(node, slugs + [wanted], page, sort, filters, True))
    return out
