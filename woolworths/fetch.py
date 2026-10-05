"""Woolworths transport: plain curl_cffi with browser-impersonated TLS. No
browser, no login, no token (validated 2026-10-05 from direct Indian egress
and through a residential AU proxy exit).

woolworths.com.au is an Angular app behind Akamai Bot Manager. Everything
the storefront shows comes from its own JSON API on the same host:

  * UI      https://www.woolworths.com.au/apis/ui/...
    Search (POST Search/products, page size capped at 36 upstream), product
    detail (product/detail/<stockcode>), bulk tiles (products/<a,b,c>),
    in-store stock (product/<stockcode>/Stores), new arrivals (POST
    Products/New), the category tree (PiesCategoriesWithSpecials, ~850 KB),
    category / specials browse (POST browse/category), autocomplete
    (search-suggestions/suggestionsb2c) and the store locator
    (StoreLocator/Stores|Store|Suburbs).

  * V3      https://www.woolworths.com.au/api/v3/ui/...
    Pick-up / Direct to Boot locations (fulfilment/stores).

  * GRAPHQL https://www.woolworths.com.au/graphql
    Ratings (bulk, with the star breakdown) and paged reviews. The search
    and browse tiles always carry a zeroed Rating block; the site fills it
    from this endpoint, and so do we. Introspection is disabled.

A session GETs the homepage once before its first API call so it carries the
Akamai cookies (_abck, bm_sz) the way a browser tab would.

Blocks: none seen. If the pod's egress ever starts answering 403/429 (or
HTML where JSON is expected), a worker moves its session to a sticky
residential exit (config.woolworths_fallback_proxy(),
config.WOOLWORTHS_FALLBACK_PROXY_COUNTRY) for
config.WOOLWORTHS_BLOCK_COOLDOWN seconds, the same shape as the kick
transport.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  WoolworthsUpstreamError  transport failure / 5xx              — retryable
  WoolworthsBlocked        403 / 429 / HTML where JSON expected — retryable on a new exit
  WoolworthsBadRequest     upstream 400                         — never retried
  WoolworthsNotFound       404 / missing entity                 — never retried
"""
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

SITE = "https://www.woolworths.com.au"
UI = SITE + "/apis/ui"
V3 = SITE + "/api/v3/ui"
GRAPHQL = SITE + "/graphql"
IMPERSONATE = "chrome"

TIMEOUT = 45
PAGE_TIMEOUT = 60
FANOUT_WORKERS = 6

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-AU,en;q=0.9",
    "referer": SITE + "/",
    "origin": SITE,
}
PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-AU,en;q=0.9",
    "upgrade-insecure-requests": "1",
}


class WoolworthsUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class WoolworthsBlocked(WoolworthsUpstreamError, Blocked):
    """403 / 429 or an HTML body where JSON was expected — retryable."""


class WoolworthsBadRequest(BadRequest):
    """Upstream 400 — the params were rejected. Never retried."""


class WoolworthsNotFound(NotFound):
    """Entity / page does not exist — never retried."""


# ---- sessions ------------------------------------------------------------------
# One curl session per worker thread. Direct egress by default; after a block
# the thread's sessions go through a sticky residential exit for a cooldown.
_local = threading.local()
_fallback_until = 0.0
_fallback_lock = threading.Lock()


def _proxy_for_new_session():
    forced = config.woolworths_proxy()
    if forced:
        return forced
    if time.time() < _fallback_until:
        return config.woolworths_fallback_proxy()
    return None


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = _proxy_for_new_session()
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        _warm(sess)
        _local.session = sess
    return sess


def _warm(sess):
    """One homepage GET so the session carries Akamai's cookies. Best
    effort: the API call that follows classifies a real block."""
    try:
        sess.get(SITE + "/", headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT, allow_redirects=True)
    except Exception:
        pass


def _drop_session():
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _note_block():
    """A 403/429 on direct egress: send new sessions through a residential
    exit for a while (no-op when no fallback country is configured)."""
    global _fallback_until
    if config.woolworths_fallback_proxy() is not None:
        with _fallback_lock:
            _fallback_until = time.time() + config.WOOLWORTHS_BLOCK_COOLDOWN


def dump_debug(name, text):
    dbg = os.environ.get("WOOLWORTHS_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


# ---- requests --------------------------------------------------------------------

def _error_message(resp):
    """{"ResponseStatus": {"Message": ...}} (the UI API) or
    {"errors": [{"message": ...}]} (GraphQL) -> the message."""
    try:
        body = resp.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    status = body.get("ResponseStatus")
    if isinstance(status, dict):
        message = status.get("Message") or status.get("ErrorCode")
        if isinstance(message, str) and message.strip():
            return message.strip()
    errors = body.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        message = errors[0].get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    message = body.get("Message")
    return message.strip() if isinstance(message, str) and message.strip() else None


def _classify(resp, label):
    status = resp.status_code
    if status == 404:
        raise WoolworthsNotFound(f"{label} not found")
    if status in (403, 429):
        dump_debug("blocked", resp.text)
        _note_block()
        raise WoolworthsBlocked(f"HTTP {status} on {label}")
    if status == 400:
        raise WoolworthsBadRequest(_error_message(resp) or f"upstream rejected {label}")
    if status == 401:
        raise WoolworthsBadRequest(f"{label} needs a Woolworths login")
    if status >= 500 or status not in (200, 204):
        raise WoolworthsUpstreamError(f"HTTP {status} on {label}")


def _json_of(resp, label):
    body = resp.text or ""
    if resp.status_code == 204 or not body.strip():
        return None
    if not body.lstrip().startswith(("{", "[")):
        # An unknown /api path answers 200 with the Angular shell, and so
        # does an Akamai interstitial: both are "not JSON".
        dump_debug("nonjson", body)
        raise WoolworthsBlocked(f"{label} returned HTML, not JSON")
    try:
        return resp.json()
    except Exception:
        dump_debug("badjson", body)
        raise WoolworthsUpstreamError(f"could not parse JSON from {label}")


def _retrying(fn):
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except WoolworthsUpstreamError as e:      # includes WoolworthsBlocked
            last = e
            _drop_session()
        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _label(url):
    return url.replace(UI, "").replace(V3, "v3:").replace(SITE, "")


def get_json(url, params=None, *, label=None):
    """GET one JSON endpoint. `params` values that are None are dropped."""
    label = label or _label(url)
    query = {k: v for k, v in (params or {}).items() if v is not None}

    def once():
        sess = _session()
        try:
            resp = sess.get(url, params=query or None, headers=HEADERS, timeout=TIMEOUT,
                            allow_redirects=True)
        except Exception as e:
            raise WoolworthsUpstreamError(f"request failed: {type(e).__name__}: {e}")
        _classify(resp, label)
        return _json_of(resp, label)

    return _retrying(once)


def post_json(url, body, *, label=None):
    """POST a JSON body to one JSON endpoint."""
    label = label or _label(url)

    def once():
        sess = _session()
        try:
            resp = sess.post(url, json=body, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        except Exception as e:
            raise WoolworthsUpstreamError(f"request failed: {type(e).__name__}: {e}")
        _classify(resp, label)
        return _json_of(resp, label)

    return _retrying(once)


def ui(path, params=None, **kwargs):
    """GET https://www.woolworths.com.au/apis/ui<path>."""
    return get_json(UI + path, params, **kwargs)


def ui_post(path, body, **kwargs):
    """POST https://www.woolworths.com.au/apis/ui<path>."""
    return post_json(UI + path, body, **kwargs)


def v3(path, params=None, **kwargs):
    """GET https://www.woolworths.com.au/api/v3/ui<path>."""
    return get_json(V3 + path, params, **kwargs)


def graphql(query, variables=None):
    """POST one GraphQL document -> the `data` member. A GraphQL-level error
    with no data is an upstream failure (the queries here are constants)."""
    body = post_json(GRAPHQL, {"query": query, "variables": variables or {}}, label="graphql") or {}
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise WoolworthsUpstreamError(_graphql_error(body) or "graphql returned no data")
    return data


def _graphql_error(body):
    errors = body.get("errors") if isinstance(body, dict) else None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return errors[0].get("message")
    return None


# ---- fan-out ------------------------------------------------------------------------

# Long-lived workers: a session is per thread and warms on the homepage, so
# a pool per call would re-download the homepage on every fan-out.
_fanout = ThreadPoolExecutor(max_workers=FANOUT_WORKERS * 4, thread_name_prefix="woolworths-fanout")


def run_parallel(fns):
    if not fns:
        return []
    if len(fns) == 1:
        return [fns[0]()]
    futures = [_fanout.submit(fn) for fn in fns[1:]]
    first = fns[0]()
    return [first] + [f.result() for f in futures]


def soft(fn, default=None):
    """Wrap an optional lookup (ratings on a listing): any upstream failure
    yields `default` instead of failing the endpoint."""
    def run():
        try:
            return fn()
        except (UpstreamError, BadRequest, NotFound):
            return default
    return run


if __name__ == "__main__":
    # Smoke test: python woolworths/fetch.py [stockcode]
    code = sys.argv[1] if len(sys.argv) > 1 else "888140"
    detail = ui(f"/product/detail/{code}")
    product = (detail or {}).get("Product") or {}
    print(f"product {code}: {product.get('DisplayName')} ${product.get('Price')}")
    hits = ui_post("/Search/products", {"SearchTerm": "milk", "PageNumber": 1, "PageSize": 5,
                                        "SortType": "TraderRelevance", "Filters": [], "IsSpecial": False,
                                        "Location": "/shop/search/products?searchTerm=milk"})
    print("search:", hits.get("SearchResultsCount"), "results")
    stores = ui("/StoreLocator/Stores", {"Max": 3, "Division": "SUPERMARKETS", "Facility": "", "postcode": "2000"})
    print("stores:", [s.get("Name") for s in stores.get("Stores") or []])
