"""Configuration for the Woolworths Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT              port the API listens on (default 8000)
    WOOLWORTHS_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                      (default: none — direct). Woolworths did not block 80
                      mixed requests from 8 parallel clients on one IP, so you
                      very likely don't need this. Set it only if you start
                      seeing failures at high volume; an Australian
                      residential proxy is the safest choice.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

WOOLWORTHS_PROXY = os.environ.get("WOOLWORTHS_PROXY") or None

# After a block the hosted version moves to a second proxy for a while; this
# kit has one proxy setting, so the fallback is simply that same proxy.
WOOLWORTHS_FALLBACK_PROXY_COUNTRY = None
WOOLWORTHS_BLOCK_COOLDOWN = 900


def woolworths_proxy():
    """Proxy for every request (None = direct)."""
    return os.environ.get("WOOLWORTHS_PROXY") or None


def woolworths_fallback_proxy():
    """Proxy to switch to after a block (None = keep the current route)."""
    return None
