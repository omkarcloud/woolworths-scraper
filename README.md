# 🛒 Woolworths Scraper

Woolworths Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Woolworths data for free.

## ✨ What Can I Get?

- 🛒 **Full details on any product in 1 call** — price, specials, barcode, ingredients, allergens, images & rating
- 🥗 **Nutrition built for diet apps** — panel per serving & per 100g, Health Star Rating, 16 dietary & 13 allergen filters
- 🏷️ **1,000+ specials every week** — half price, was-price, savings & multibuy offers
- 📍 **Live shelf stock at up to 50 nearby stores** — plus trading hours, facilities & pick-up points

## 🎥 Example: A Full Woolworths Product

```json
{
  "product": {
    "id": 814479,
    "name": "Cadbury Dairy Milk Chocolate Block 180g",
    "link": "https://www.woolworths.com.au/shop/productdetails/814479/cadbury-dairy-milk-chocolate-block",
    "barcode": "9300617064879",
    "brand": "Cadbury",
    "package_size": "180g",
    "image": "https://cdn1.woolworths.media/content/wowproductimages/large/814479.jpg",
    "rating": { "average": 4.85, "reviews_count": 96, "distribution": {"5": 85, "4": 8, "3": 3, "2": 0, "1": 0} },
    "pricing": {
      "price": 4.8,
      "currency": "AUD",
      "was_price": 8.0,
      "savings_amount": 3.2,
      "unit_price": 2.67,
      "unit_price_measure": "100G",
      "is_on_special": true
    },
    "promotion": { "type": "Special", "label": "Save $3.20", "badge": "40% Off" },
    "availability": { "is_in_stock": true, "is_for_delivery": true, "supply_limit": 36 },
    "dietary": { "contains": ["Milk", "Soy"], "may_contain": ["Tree Nuts", "Peanuts", "Gluten", "Wheat"] },
    "description": "Deliciously smooth and creamy Cadbury Dairy Milk milk chocolate.",
    "ingredients": "Full Cream Milk, Sugar, Cocoa Butter, Cocoa Mass, Milk Solids, Emulsifiers (Soy Lecithin, 476), Flavours.",
    "nutrition": {
      "serving_size": "25.0 G",
      "servings_per_pack": 7.2,
      "nutrients": [
        { "name": "Energy", "per_serving": {"amount": 560.0, "unit": "kJ", "qualifier": null}, "per_100": {"amount": 2240.0, "unit": "kJ", "qualifier": null} },
        { "name": "Protein", "per_serving": {"amount": 1.8, "unit": "g", "qualifier": null}, "per_100": {"amount": 7.4, "unit": "g", "qualifier": null} }
      ]
    },
    "country_of_origin": { "country": null, "statement": "Made in Australia from imported and local ingredients" },
    "images": ["https://cdn0.woolworths.media/content/wowproductimages/large/814479.jpg", "https://cdn0.woolworths.media/content/wowproductimages/large/814479_1.jpg"]
  }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Woolworths Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/woolworths-scraper
cd woolworths-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/products/details?product=814479"
```

```json
{
  "product": {
    "id": 814479,
    "name": "Cadbury Dairy Milk Chocolate Block 180g",
    "link": "https://www.woolworths.com.au/shop/productdetails/814479/cadbury-dairy-milk-chocolate-block",
    "barcode": "9300617064879",
    "brand": "Cadbury",
    "package_size": "180g",
    "rating": { "average": 4.85, "reviews_count": 96 },
    "pricing": {
      "price": 4.8,
      "currency": "AUD",
      "was_price": 8.0,
      "unit_price": 2.67,
      "unit_price_measure": "100G",
      "is_on_special": true
    },
    "promotion": { "label": "Save $3.20", "badge": "40% Off" },
    "dietary": { "contains": ["Milk", "Soy"] },
    "ingredients": "Full Cream Milk, Sugar, Cocoa Butter, Cocoa Mass, Milk Solids, Emulsifiers (Soy Lecithin, 476), Flavours.…"
  }
}
```

All 17 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

17 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Product Details | `/products/details` | Everything about one product in a single call |
| Search Products | `/products/search` | 36 products per page; filter by brand, diet, allergens, specials |
| Autocomplete | `/products/autocomplete` | Search suggestions as you type |
| Product by Barcode | `/products/barcode` | Scan a barcode, get the product with live price |
| Bulk Products | `/products/bulk` | Up to 20 products with prices and ratings in one call |
| Product Nutrition | `/products/nutrition` | Nutrition panel, ingredients, allergens, Health Star Rating |
| Product Reviews | `/products/reviews` | Customer reviews with star breakdown, up to 50 per page |
| Product Stock in Stores | `/products/stock` | Which nearby stores have it on the shelf right now |
| New Products | `/products/new` | Everything newly added to the range |
| Specials / Specials Types | `/specials`, `/specials/types` | Half Price and every other specials shelf, with savings |
| Categories | `/categories` | The full category tree with IDs, slugs and links |
| Category Products | `/categories/products` | Every product in any category, filterable and sortable |
| Search Stores / Store Details | `/stores/search`, `/stores/details` | Stores near you with hours, facilities and coordinates |
| Pickup Locations | `/stores/pickup-locations` | Pick up and Direct to Boot points near a postcode |
| Search Locations | `/locations/search` | Australian suburbs with postcode and coordinates |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-woolworths-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-woolworths-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-woolworths-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/products/details",
    params={"product": "814479"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Woolworths Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/woolworths-scraper-github-whatsapp)

[![Ask Us by Email about Woolworths Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Woolworths%20Scraper%20API&body=I%20need%20help%20using%20the%20Woolworths%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/woolworths-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/woolworths-scraper)