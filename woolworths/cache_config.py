"""Cache TTL per /woolworths/* endpoint (cache.py, keyed on the validated
params).

Woolworths reprices once a week: the catalogue (and every special) rolls
over on Wednesday, with occasional mid-week markdowns. Shelf prices are
therefore safe for hours; in-store stock moves through the day.
"""
from datetime import timedelta

# --- products ----------------------------------------------------------------
# Listings: prices + specials flags + stock flags for 36 products.
SEARCH_CACHE = timedelta(hours=2)
BROWSE_CACHE = timedelta(hours=2)
SPECIALS_CACHE = timedelta(hours=2)
NEW_CACHE = timedelta(hours=6)
# One product: price, promotion and the (static) long-form blocks.
PRODUCT_CACHE = timedelta(hours=2)
BULK_CACHE = timedelta(hours=1)
BARCODE_CACHE = timedelta(hours=6)
# Ingredients and the nutrition panel change only with a reformulation.
NUTRITION_CACHE = timedelta(days=3)
# A product gains a review now and then.
REVIEWS_CACHE = timedelta(hours=12)
# Shelf stock at a store.
STOCK_CACHE = timedelta(minutes=30)
AUTOCOMPLETE_CACHE = timedelta(days=1)

# --- catalogue ---------------------------------------------------------------
# The tree itself; the specials shelves under it change weekly.
CATEGORIES_CACHE = timedelta(hours=12)
SPECIALS_TYPES_CACHE = timedelta(hours=6)

# --- stores ------------------------------------------------------------------
# Carries is_open and today's hours.
STORES_CACHE = timedelta(minutes=30)
STORE_CACHE = timedelta(minutes=30)
PICKUP_CACHE = timedelta(days=1)
LOCATIONS_CACHE = timedelta(days=30)
