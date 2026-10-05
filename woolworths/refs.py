"""Woolworths reference parsing: ONE param per input that auto-detects its
forms (tripadvisor QueryOrIdField convention — never a sibling `url`/`id`
pair).

  product    888140 (the stockcode)
             | https://www.woolworths.com.au/shop/productdetails/888140/woolworths-full-cream-milk
  category   1_DEB537E (the node id the site's own API uses)
             | bakery | bakery/packaged-bread-bakery (the slug path of the browse link)
             | https://www.woolworths.com.au/shop/browse/bakery/packaged-bread-bakery
             | specialsgroup.3676 | https://www.woolworths.com.au/shop/browse/specials/half-price
  store      8964 (the store number)
             | https://www.woolworths.com.au/shop/storelocator/nsw-barangaroo-barangaroo-metro-8964
  location   2000 (postcode) | -33.8688,151.2093 (latitude,longitude) | Bondi (suburb name)
  barcode    9300633556150 (EAN-8 / UPC-A / EAN-13 / GTIN-14 digits)

Category slug paths and links resolve against the live category tree
(shared.category_node); this module only normalises the spelling.
"""
import re
from urllib.parse import urlparse

SITE = "https://www.woolworths.com.au"
IMAGE_HOST = "https://cdn0.woolworths.media"

_STOCKCODE_RE = re.compile(r"^\d{1,12}$")
_NODE_ID_RE = re.compile(r"^(?:1[_-][A-Za-z0-9]+(?:_SPECIALS)?|specialsgroup(?:\.[A-Za-z0-9_\-]+)*)$", re.I)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
_BARCODE_RE = re.compile(r"^\d{8,14}$")
_POSTCODE_RE = re.compile(r"^\d{4}$")
_LATLNG_RE = re.compile(r"^(-?\d{1,3}(?:\.\d+)?)\s*[,; ]\s*(-?\d{1,3}(?:\.\d+)?)$")
MAX_BULK = 20


def _is_url(value):
    low = value.lower()
    return low.startswith(("http://", "https://", "//", "woolworths.com.au/", "www.woolworths.com.au/"))


def _segments(value):
    """A woolworths.com.au link -> lower-cased path segments. Raises
    ValueError for another site."""
    url = value
    if url.startswith("//"):
        url = "https:" + url
    elif not url.lower().startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not (host == "woolworths.com.au" or host.endswith(".woolworths.com.au")):
        raise ValueError("not a woolworths.com.au link")
    return [s for s in parsed.path.split("/") if s]


# ---- links ------------------------------------------------------------------------

def product_link(stockcode, slug=None):
    if not stockcode:
        return None
    link = f"{SITE}/shop/productdetails/{stockcode}"
    return f"{link}/{slug}" if slug else link


def category_link(slugs):
    """['bakery', 'packaged-bread-bakery'] -> the browse link."""
    slugs = [s for s in (slugs or []) if s]
    return f"{SITE}/shop/browse/" + "/".join(slugs) if slugs else None


def search_link(query):
    from urllib.parse import quote
    return f"{SITE}/shop/search/products?searchTerm={quote(query)}" if query else None


def absolute_link(path):
    """A site-relative asset path ('/content/promotiontags/x.png') -> an
    absolute link on the image CDN; absolute links pass through."""
    if not isinstance(path, str) or not path.strip():
        return None
    path = path.strip()
    if path.startswith("//"):
        return "https:" + path
    if path.startswith("http"):
        return path
    return IMAGE_HOST + (path if path.startswith("/") else "/" + path)


# ---- resolvers ----------------------------------------------------------------------

def resolve_product(value):
    """Stockcode or a woolworths.com.au product link -> the stockcode (str)."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("product is required")
    if _is_url(value):
        try:
            segments = _segments(value)
        except ValueError:
            raise ValueError("product must be a woolworths.com.au product link or a stockcode")
        lowered = [s.lower() for s in segments]
        candidate = None
        if "productdetails" in lowered:
            index = lowered.index("productdetails")
            if index + 1 < len(segments):
                candidate = segments[index + 1]
        if not candidate or not _STOCKCODE_RE.match(candidate):
            raise ValueError("product link must look like "
                             "https://www.woolworths.com.au/shop/productdetails/888140/woolworths-full-cream-milk")
        value = candidate
    if not _STOCKCODE_RE.match(value):
        raise ValueError("product must be a Woolworths stockcode (888140) or a woolworths.com.au product link")
    return str(int(value))


def resolve_products(value):
    """Comma-separated stockcodes / links -> [stockcode, ...] (deduped,
    order kept, at most MAX_BULK)."""
    out = []
    for raw in str(value or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        code = resolve_product(raw)
        if code not in out:
            out.append(code)
    if not out:
        raise ValueError("products is required")
    if len(out) > MAX_BULK:
        raise ValueError(f"at most {MAX_BULK} products per call")
    return out


def resolve_category(value):
    """Category node id, slug path or browse link -> {"id": node id} or
    {"path": [slug, ...]}. `specials` as the first slug is the site's
    specials root."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("category is required")
    if _is_url(value):
        try:
            segments = _segments(value)
        except ValueError:
            raise ValueError("category must be a woolworths.com.au browse link, a category id or a slug path")
        lowered = [s.lower() for s in segments]
        if "browse" not in lowered or lowered.index("browse") + 1 >= len(lowered):
            raise ValueError("category link must look like https://www.woolworths.com.au/shop/browse/bakery")
        return {"path": lowered[lowered.index("browse") + 1:]}
    if _NODE_ID_RE.match(value):
        return {"id": value}
    path = [s.strip().lower() for s in value.strip("/").split("/") if s.strip()]
    if not path or not all(_SLUG_RE.match(s) for s in path):
        raise ValueError("category must be a category id (1_DEB537E), a slug path "
                         "(bakery/packaged-bread-bakery) or a woolworths.com.au browse link")
    return {"path": path}


def resolve_store(value):
    """Store number or a woolworths.com.au store locator link -> the store number."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("store is required")
    if _is_url(value):
        try:
            segments = _segments(value)
        except ValueError:
            raise ValueError("store must be a woolworths.com.au store link or a store number")
        match = re.search(r"(\d{3,6})$", segments[-1]) if segments else None
        if not match:
            raise ValueError("store link must end in the store number "
                             "(https://www.woolworths.com.au/shop/storelocator/nsw-barangaroo-barangaroo-metro-8964)")
        value = match.group(1)
    if not re.match(r"^\d{1,6}$", value):
        raise ValueError("store must be a Woolworths store number (8964) or a woolworths.com.au store link")
    return value


def resolve_barcode(value):
    value = re.sub(r"[\s\-]", "", str(value or ""))
    if not value:
        raise ValueError("barcode is required")
    if not _BARCODE_RE.match(value):
        raise ValueError("barcode must be 8 to 14 digits (9300633556150)")
    return value


def resolve_location(value):
    """Postcode, 'latitude,longitude' or a suburb name ->
    {"postcode"} | {"latitude", "longitude"} | {"suburb"}."""
    value = " ".join(str(value or "").split())
    if not value:
        raise ValueError("location is required")
    if _POSTCODE_RE.match(value):
        return {"postcode": value}
    match = _LATLNG_RE.match(value)
    if match:
        latitude, longitude = float(match.group(1)), float(match.group(2))
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("location coordinates are out of range")
        return {"latitude": latitude, "longitude": longitude}
    if value.isdigit():
        raise ValueError("location must be a 4-digit Australian postcode, 'latitude,longitude' or a suburb name")
    if len(value) < 3:
        raise ValueError("location suburb name must be at least 3 characters")
    return {"suburb": value}


def resolve_postcode(value):
    value = str(value or "").strip()
    if not _POSTCODE_RE.match(value):
        raise ValueError("postcode must be a 4-digit Australian postcode (2000)")
    return value
