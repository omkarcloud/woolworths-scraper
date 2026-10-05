"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. Functions take the validated values the API passes them, so
`product` is a stockcode string and `category` / `location` are the small
dicts woolworths/refs.py resolves a link, slug or postcode into.
"""
import json
import os

from woolworths import categories, products, refs

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a stockcode or any woolworths.com.au product link
    save("product_814479.json", products.details(refs.resolve_product("814479")))

    # 36 products per page, with ratings and filters to narrow by
    save("search_chocolate.json", products.search("chocolate"))

    # this week's half-price shelf
    save("specials_half_price.json", categories.specials(type="half_price"))
