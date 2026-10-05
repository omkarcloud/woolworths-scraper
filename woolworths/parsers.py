"""Woolworths normalizers: the storefront's PascalCase API objects -> one
clean snake_case shape per entity.

Output conventions (shared with the other scrapers here): `link` for
canonical page URLs (always absolute), `image` for pictures, `*_count` for
counters, `is_*`/`has_*` for booleans, ISO-8601 UTC timestamps
("2026-09-15T13:49:00Z") and ISO dates ("2026-10-07"), numbers as numbers,
prices as a numeric amount next to one `currency` ("AUD"), null for missing.

One product shape everywhere (search, browse, specials, new, bulk, barcode);
the details endpoint adds the long-form blocks to the same object:

  product  {id, name, link, barcode, brand, variety, package_size, image,
            is_* flags, rating, pricing, in_store_pricing, promotion,
            availability, dietary, categories, seller}
           + details: description, ingredients, nutrition, country_of_origin,
             storage/usage instructions, warnings, images, features,
             dimensions, variants, delivery

Deliberately dropped as noise:
  * viewer state — QuantityInTrolley, IsInTrolley, HasBeenBoughtBefore,
    IsPersonalisedByPurchaseHistory, IsInFamily (anonymous reader);
  * layout / tracking — TileID, Source, Diagnostics, AdID, AdIndex,
    AdStatus, FulfilmentStoreId, AttributionToken*, tag colours
    (BackgroundColor / BorderColor / TextColor), TagType, UrlOverride,
    RichRelevance*, DiagnosticsData, SeoMetaTags, DisplayCoachMarks, the
    `@context`-style keys;
  * presentation-only duplicates — CupString / InstoreCupString (the unit
    price is kept as amount + measure), SupplyLimitMessage /
    MaxSupplyLimitMessage (supply_limit is kept), SmallFormatDescription /
    FullDescription (= the name), the tile's own Description (= name with a
    <br>), PricePerKGLabel, HideWasSavedPrice, IsCentreTag / HasHeaderTag /
    IsFooterEnabled, TagContent HTML (its text and numbers are kept),
    TradingHourForDisplay (parsed into day + opens_at + closes_at);
  * the zeroed Rating block on tiles (ratings come from the site's GraphQL
    endpoint instead) and RatingSum / per-star percentages (derivable);
  * internal ids — GtinFormat, SupplyLimitSource, sap*no codes,
    vendorarticleid, vendorcostprice (always null), specialsgroupid,
    Market.AdvertId / PlatformCategoryId / Variant_LegacyId, SuburbId /
    AreaId on pick-up points, GeoLevel on stores;
  * the ~60 boolean attribute columns that are "False"/null on a product
    (only the true ones are listed, under `features`).
"""
import html
import json
import re
from datetime import datetime, timezone

from woolworths import refs

CURRENCY = "AUD"

_TAG_RE = re.compile(r"<[^>]+>")
_BREAK_RE = re.compile(r"<\s*(?:br\s*/?|/p|/div|/li|/h[1-6]|/tr)\s*>", re.I)
_LI_RE = re.compile(r"<\s*li[^>]*>", re.I)
_FRACTION_RE = re.compile(r"(\.\d{6})\d+")
_QUANTITY_RE = re.compile(r"^\s*([<>≤≥~])?\s*(-?\d+(?:[.,]\d+)?)\s*(.*?)\s*$")
_OFFER_GROUP_RE = re.compile(r"/OfferGroup/(\d+)", re.I)
_HOURS_RE = re.compile(r"^\s*([A-Za-z]{3})[a-z]*\s*:\s*(\d{2})(\d{2})\s*-\s*(\d{2})(\d{2})\s*$")
_DAYS = {"mon": "monday", "tue": "tuesday", "wed": "wednesday", "thu": "thursday",
         "fri": "friday", "sat": "saturday", "sun": "sunday"}


# ---- value helpers ------------------------------------------------------------
# (kept local so the package stands alone, like the other site packages)

def to_int(value):
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def to_float(value):
    if isinstance(value, bool):
        return None
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def text(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def bool_or_none(value):
    return value if isinstance(value, bool) else None


def flag(value):
    """The attribute table spells booleans as "True"/"False" strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low == "true":
            return True
        if low == "false":
            return False
    return None


def money(value):
    """A price amount; the API's 0 / 0.0 for "no price" stays a number only
    where the caller says it is meaningful."""
    number = to_float(value)
    return round(number, 2) if number is not None else None


def positive_money(value):
    number = money(value)
    return number if number else None


def clean_html(value):
    """Rich text -> plain text with paragraph / list breaks kept."""
    if not isinstance(value, str) or not value.strip():
        return None
    out = _LI_RE.sub("- ", value)
    out = _BREAK_RE.sub("\n", out)
    out = html.unescape(_TAG_RE.sub("", out)).replace("\xa0", " ").replace("\r", "")
    lines = [" ".join(line.split()) for line in out.split("\n")]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out or None


def split_list(value, sep=","):
    """'Dairy Free,Egg Free' -> ['Dairy Free', 'Egg Free'] ([] if absent)."""
    if not isinstance(value, str):
        return []
    out = []
    for item in value.split(sep):
        item = item.strip()
        if item and item not in out:
            out.append(item)
    return out


def json_value(value):
    """A JSON document carried as a string attribute -> its value (None on junk)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except ValueError:
        return None


def _parse_dt(value):
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    if raw.startswith("0001-"):
        return None
    raw = _FRACTION_RE.sub(r"\1", raw)          # .NET 7-digit fractions
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def iso_datetime(value):
    """'2026-10-08T20:55:51.3214870+11:00' -> '2026-10-08T09:55:51Z' (UTC)."""
    dt = _parse_dt(value)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def iso_date(value):
    """'2026-10-07T00:00:00.0000000Z' -> '2026-10-07' (the calendar date as
    written; these are day-granular fields)."""
    if not value or not isinstance(value, str):
        return None
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", value.strip())
    if not match or match.group(1).startswith("0001-"):
        return None
    return match.group(1)


def utc_offset(value):
    """The store's 'GMTZone' ('11:0', '9:30', '-5:0') -> '+11:00'."""
    if not isinstance(value, str) or ":" not in value:
        return None
    hours, _, minutes = value.strip().partition(":")
    try:
        h, m = int(hours), int(minutes or 0)
    except ValueError:
        return None
    sign = "-" if hours.strip().startswith("-") else "+"
    return f"{sign}{abs(h):02d}:{m:02d}"


def pagination(page, per_page, total):
    total = to_int(total) or 0
    return {"page": page, "items_per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page if total else 0,
            "total_count": total}


# ---- attribute table ------------------------------------------------------------

# AdditionalAttributes columns that are real yes/no product features. Listed
# under `features` only when "True" (they are "False"/null on almost every
# product, e.g. `antibacterial` on bread).
_FEATURE_FLAGS = [
    "addedvitaminsandminerals", "alcoholfree", "anti-dandruff", "antibacterial", "antioxidant",
    "antiseptic", "bpafree", "dermatologicallyapproved", "dermatologistrecommended",
    "dermatologisttested", "fragrance-free", "freezable", "hypo-allergenic", "microwaveable",
    "microwavesafe", "non-comedogenic", "oilfree", "ophthalmologistapproved",
    "ophthalmologisttested", "ovencook", "paba-free", "parabenfree", "phbalanced", "soap-free",
    "sulfatefree", "sweatresistant", "vegetarian", "waterresistant",
]
_FEATURE_NAMES = {
    "addedvitaminsandminerals": "added_vitamins_and_minerals", "alcoholfree": "alcohol_free",
    "anti-dandruff": "anti_dandruff", "bpafree": "bpa_free",
    "dermatologicallyapproved": "dermatologically_approved",
    "dermatologistrecommended": "dermatologist_recommended",
    "dermatologisttested": "dermatologist_tested", "fragrance-free": "fragrance_free",
    "hypo-allergenic": "hypoallergenic", "microwavesafe": "microwave_safe",
    "non-comedogenic": "non_comedogenic", "oilfree": "oil_free",
    "ophthalmologistapproved": "ophthalmologist_approved",
    "ophthalmologisttested": "ophthalmologist_tested", "ovencook": "oven_cook",
    "paba-free": "paba_free", "parabenfree": "paraben_free", "phbalanced": "ph_balanced",
    "soap-free": "soap_free", "sulfatefree": "sulfate_free", "sweatresistant": "sweat_resistant",
    "waterresistant": "water_resistant",
}


def _attrs(product):
    attrs = product.get("AdditionalAttributes") if isinstance(product, dict) else None
    return attrs if isinstance(attrs, dict) else {}


def features(attrs):
    return [_FEATURE_NAMES.get(key, key) for key in _FEATURE_FLAGS if flag(attrs.get(key)) is True]


def dietary(attrs):
    """Health star rating and the label claims. `allergen_free_claims` are
    the pack's "X Free" statements, `contains` / `may_contain` its allergen
    declarations."""
    block = {
        "health_star_rating": to_float(attrs.get("healthstarrating")),
        "lifestyle": split_list(attrs.get("lifestyleanddietarystatement")),
        "allergen_free_claims": split_list(attrs.get("allergystatement")),
        "contains": split_list(attrs.get("allergencontains")),
        "may_contain": split_list(attrs.get("allergenmaybepresent")),
        "is_gluten_containing": flag(attrs.get("containsgluten")),
        "is_nut_containing": flag(attrs.get("containsnuts")),
    }
    return block


def categories(attrs):
    """Where the product sits: the storefront departments / categories /
    subcategories it is listed under and Woolworths' merchandise hierarchy."""
    departments = []
    for row in json_value(attrs.get("PiesProductDepartmentsjson")) or []:
        if isinstance(row, dict) and row.get("Id"):
            departments.append({"id": text(row.get("Id")), "name": text(row.get("Description"))})
    if not departments:
        departments = [{"id": None, "name": name}
                       for name in json_value(attrs.get("piesdepartmentnamesjson")) or [] if text(name)]
    primary_id = text(attrs.get("PiesProductDepartmentNodeId"))
    primary = next((d for d in departments if d["id"] == primary_id), None) if primary_id else None
    merchandise = {
        "department": text(attrs.get("sapdepartmentname")),
        "category": text(attrs.get("sapcategoryname")),
        "subcategory": text(attrs.get("sapsubcategoryname")),
        "segment": text(attrs.get("sapsegmentname")),
    }
    return {
        "primary_department": primary or (departments[0] if departments else None),
        "departments": departments,
        "categories": _unique(json_value(attrs.get("piescategorynamesjson"))),
        "subcategories": _unique(json_value(attrs.get("piessubcategorynamesjson"))),
        "merchandise_hierarchy": merchandise if any(merchandise.values()) else None,
    }


def _unique(values):
    out = []
    for value in values if isinstance(values, list) else []:
        value = text(value)
        if value and value not in out:
            out.append(value)
    return out


# ---- ratings ------------------------------------------------------------------

def rating(raw):
    """The GraphQL rating object -> {average, ratings_count, reviews_count,
    distribution}. None when the product has no ratings."""
    if not isinstance(raw, dict):
        return None
    count = to_int(raw.get("ratingCount")) or 0
    reviews = to_int(raw.get("reviewCount")) or 0
    if not count and not reviews:
        return None
    return {
        "average": to_float(raw.get("average")),
        "ratings_count": count,
        "reviews_count": reviews,
        "distribution": {
            "5": to_int(raw.get("fiveStarCount")) or 0,
            "4": to_int(raw.get("fourStarCount")) or 0,
            "3": to_int(raw.get("threeStarCount")) or 0,
            "2": to_int(raw.get("twoStarCount")) or 0,
            "1": to_int(raw.get("oneStarCount")) or 0,
        },
    }


def ratings_by_id(data):
    """The bulk ratings GraphQL answer -> {stockcode str: rating}."""
    out = {}
    for row in (data or {}).get("products") or []:
        if isinstance(row, dict) and row.get("id") is not None:
            parsed = rating(row.get("rating"))
            if parsed:
                out[str(row["id"])] = parsed
    return out


def review(raw):
    return {
        "rating": to_int(raw.get("rating")),
        "text": text(raw.get("body")),
        "author": text(raw.get("member")),
        "source": text(raw.get("source")),
        "created_at": iso_datetime(raw.get("createdDate")),
    }


# ---- pricing / promotion ----------------------------------------------------------

def _unit_price(amount, measure, has):
    amount = money(amount)
    if not has or not amount:
        return None, None
    return amount, text(measure)


def pricing(p):
    """Online price block. `unit_price` is the comparison price per
    `unit_price_measure` (e.g. 0.66 per "100G"). `price` is null when the
    product is not sold online right now."""
    unit_price, measure = _unit_price(p.get("CupPrice"), p.get("CupMeasure"), p.get("HasCupPrice"))
    price = positive_money(p.get("Price"))
    was = positive_money(p.get("WasPrice"))
    return {
        "price": price,
        "currency": CURRENCY,
        "was_price": was if was and price and was > price else None,
        "savings_amount": positive_money(p.get("SavingsAmount")),
        "unit_price": unit_price,
        "unit_price_measure": measure,
        "is_on_special": bool_or_none(p.get("IsOnSpecial")),
        "is_half_price": bool_or_none(p.get("IsHalfPrice")),
        "is_member_special": bool_or_none(p.get("IsEdrSpecial")),
        "sold_by": text(p.get("Unit")),
        "minimum_quantity": to_float(p.get("MinimumQuantity")),
        "weight_range_price": _weight_range(p),
    }


def _weight_range(p):
    """Loose / random-weight items (a whole chicken) carry a min and max
    pack price instead of one price."""
    low, high = positive_money(p.get("MinWeightPrice")), positive_money(p.get("MaxWeightPrice"))
    if low is None and high is None:
        return None
    return {"min_price": low, "max_price": high}


def in_store_pricing(p):
    unit_price, measure = _unit_price(p.get("InstoreCupPrice"), p.get("CupMeasure"), p.get("InstoreHasCupPrice"))
    price = positive_money(p.get("InstorePrice"))
    was = positive_money(p.get("InstoreWasPrice"))
    if price is None and unit_price is None:
        return None
    return {
        "price": price,
        "currency": CURRENCY,
        "was_price": was if was and price and was > price else None,
        "savings_amount": positive_money(p.get("InstoreSavingsAmount")),
        "unit_price": unit_price,
        "unit_price_measure": measure,
        "is_on_special": bool_or_none(p.get("InstoreIsOnSpecial")),
    }


def _snake(name):
    out = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name))
    return re.sub(r"[^a-z0-9]+", "_", out.lower()).strip("_")


def _snake_dict(value):
    """A small upstream dict whose exact fields vary by promotion ->
    snake_case keys, scalars only."""
    if not isinstance(value, dict):
        return None
    out = {}
    for key, item in value.items():
        if isinstance(item, (str, int, float, bool)) or item is None:
            out[_snake(key)] = item.strip() or None if isinstance(item, str) else item
    return out if any(v is not None for v in out.values()) else None


def promotion(p):
    """The promotional tags on a tile -> one block, or None when the product
    carries no promotion.

      type       the header tag's promotion code (Special, LowPrice, ...)
      label      the header text ("Save $3.20", "EVERYDAY LOW PRICE")
      badge      the roundel text ("Half Price", "40% Off")
      multibuy   {quantity, price, unit_price_text} for "2 for $10"
    """
    header = p.get("HeaderTag") if isinstance(p.get("HeaderTag"), dict) else {}
    centre = p.get("CentreTag") if isinstance(p.get("CentreTag"), dict) else {}
    image = p.get("ImageTag") if isinstance(p.get("ImageTag"), dict) else {}
    footer = p.get("FooterTag") if isinstance(p.get("FooterTag"), dict) else {}

    multibuy = None
    data = centre.get("MultibuyData")
    if isinstance(data, dict) and (data.get("Quantity") or data.get("Price")):
        multibuy = {"quantity": to_int(data.get("Quantity")), "price": money(data.get("Price")),
                    "currency": CURRENCY, "unit_price_text": text(data.get("CupTag"))}
    member = _snake_dict(centre.get("MemberPriceData")) or _snake_dict(centre.get("FFPVMemberPriceData"))
    offer = _OFFER_GROUP_RE.search(centre.get("TagContent") or "") if isinstance(centre.get("TagContent"), str) else None
    promotion_type = text(header.get("Promotion"))
    kinds = [text(tag.get("PromotionType")) for tag in (centre, image, footer)]
    kind = next((k for k in kinds if k and k != "NOT_SET"), None)

    block = {
        "type": promotion_type or kind,
        "label": clean_html(header.get("Content")),
        "badge": text(image.get("FallbackText")),
        "badge_image": refs.absolute_link(image.get("TagContent")) if text(image.get("FallbackText")) else None,
        "offer_text": text(centre.get("TagContentText")) or clean_html(centre.get("TagContent")),
        "footer_text": clean_html(footer.get("TagContent")),
        "multibuy": multibuy,
        "member_price": member,
        "offer_group_id": offer.group(1) if offer else None,
        "is_rewards_card_required": True if any(
            tag.get("IsRegisteredRewardCardPromotion") is True for tag in (centre, image, footer)) else False,
    }
    has_any = any(block[k] for k in ("type", "label", "badge", "offer_text", "footer_text", "multibuy",
                                    "member_price", "offer_group_id"))
    return block if has_any else None


def availability(p):
    return {
        "is_in_stock": bool_or_none(p.get("IsInStock")),
        "is_available": bool_or_none(p.get("IsAvailable")),
        "is_purchasable": bool_or_none(p.get("IsPurchasable")),
        "is_available_in_store": bool_or_none(p.get("InstoreIsAvailable")),
        "is_for_delivery": bool_or_none(p.get("IsForDelivery")),
        "is_for_collection": bool_or_none(p.get("IsForCollection")),
        "is_for_express": bool_or_none(p.get("IsForExpress")),
        "supply_limit": to_int(p.get("SupplyLimit")),
        "next_availability_date": iso_date(p.get("NextAvailabilityDate")),
        "restriction_message": clean_html(p.get("ProductRestrictionMessage")),
        "warning_message": clean_html(p.get("ProductWarningMessage")),
    }


# ---- marketplace (Everyday Market) -----------------------------------------------

def seller(p, attrs):
    """The third-party seller of an Everyday Market item (None for products
    Woolworths sells itself)."""
    info = p.get("ThirdPartyProductInfo") if isinstance(p.get("ThirdPartyProductInfo"), dict) else {}
    name = text(p.get("Vendor")) or text(info.get("VendorName")) or text(attrs.get("Market.Seller_BusinessName"))
    if not name and not p.get("IsMarketProduct"):
        return None
    vendor = info.get("ThirdPartyVendorDeliveryInfo") if isinstance(info.get("ThirdPartyVendorDeliveryInfo"), dict) else {}
    free = bool_or_none(p.get("IsFreeShipping"))
    if free is None:
        free = flag(attrs.get("Market.IsFreeShipping"))
    return {
        "id": text(vendor.get("VendorId")) or text(attrs.get("Market.Seller_Id")),
        "name": name,
        "is_free_shipping": free,
        "dispatch_note": text(vendor.get("DayRangeDispatchNote")),
    }


def market_delivery(p, attrs):
    """Shipping terms of an Everyday Market item (details only). The
    estimate is for the site's default delivery postcode."""
    info = p.get("ThirdPartyProductInfo") if isinstance(p.get("ThirdPartyProductInfo"), dict) else None
    if not info:
        return None
    vendor = info.get("ThirdPartyVendorDeliveryInfo") if isinstance(info.get("ThirdPartyVendorDeliveryInfo"), dict) else {}
    delivery = info.get("MarketProductDeliveryInfo") if isinstance(info.get("MarketProductDeliveryInfo"), dict) else {}
    days = delivery.get("EstimatedDeliveryDays") if isinstance(delivery.get("EstimatedDeliveryDays"), dict) else {}
    return {
        "flat_fee": money(info.get("DeliveryFlatFee")),
        "freight_amount": money(delivery.get("FreightAmount")),
        "currency": CURRENCY,
        "shipment_type": text(vendor.get("ShipmentType")),
        "dispatch_note": text(vendor.get("DayRangeDispatchNote")),
        "estimated_from": iso_datetime(vendor.get("MinimumDeliveryTime")),
        "estimated_to": iso_datetime(vendor.get("MaximumDeliveryTime")),
        "estimated_min_days": to_int(days.get("Min")) if days else to_int(attrs.get("Market.SellerMinDaysToDelivery")),
        "estimated_max_days": to_int(days.get("Max")) if days else to_int(attrs.get("Market.SellerMaxDaysToDelivery")),
        "estimated_for": {
            "postcode": text(delivery.get("Postcode")),
            "suburb": text(delivery.get("Suburb")),
            "state": text(delivery.get("State")),
        } if delivery.get("Postcode") else None,
        "is_undeliverable": bool_or_none(delivery.get("IsUndeliverable")),
        "is_po_box_deliverable": flag(attrs.get("Market.IsPoBoxDeliverable")),
        "is_bulky": flag(attrs.get("Market.IsBulky")),
        "is_oversized": flag(attrs.get("Market.IsOversized")),
        "is_change_of_mind_returnable": (not flag(attrs.get("Market.No_Change_Of_Mind_Returns")))
        if flag(attrs.get("Market.No_Change_Of_Mind_Returns")) is not None else None,
        "max_purchase_quantity": to_int(attrs.get("Market.MaxPurchaseQuantity")),
    }


def market_variants(attrs):
    """An Everyday Market item's variant set, rebuilt from the flattened
    `Market.Variant_*` attribute columns:

        {title, options: [{name, value, values: [...]}], product_ids: [...]}

    `value` is THIS product's choice, `values` every choice on offer and
    `product_ids` the sibling stockcodes."""
    keys = split_list(attrs.get("Market.Variant_Option_Keys"))
    siblings = [to_int(v) for v in split_list(attrs.get("Market.VariantProductIds")) if to_int(v) is not None]
    if not keys and not siblings:
        return None
    options = []
    for key in keys:
        value = names = position = None
        for column, raw in attrs.items():
            if not column.startswith("Market.Variant_") or not column.endswith(("_" + key, "_" + key + "_Names")):
                continue
            if column.startswith("Market.Variant_OptionValue_") and column.endswith("_Names"):
                names = split_list(raw, "|")
            elif column.startswith("Market.Variant_OptionValue_"):
                value = text(raw)
            elif column.startswith("Market.Variant_OptionPosition_"):
                position = to_int(raw)
        options.append({"name": key, "value": value, "values": names or [], "_position": position})
    options.sort(key=lambda o: (o["_position"] is None, o["_position"] or 0))
    for option in options:
        option.pop("_position")
    return {
        "title": text(attrs.get("Market.Variant_Title")),
        "is_primary": flag(attrs.get("Market.IsPrimaryVariant")),
        "options": options,
        "product_ids": siblings,
    }


# ---- products ---------------------------------------------------------------------

def is_real_product(p):
    """An unknown stockcode still answers 200 with an empty shell (no name,
    price 0, default image)."""
    return isinstance(p, dict) and bool(text(p.get("Name")) or text(p.get("DisplayName")))


def product(p, rating_block=None):
    """One product tile (search / browse / bulk / detail's Product) -> the
    shared product shape. `rating_block` is the parsed GraphQL rating."""
    attrs = _attrs(p)
    stockcode = to_int(p.get("Stockcode"))
    return {
        "id": stockcode,
        "name": text(p.get("DisplayName")) or text(p.get("Name")),
        "link": refs.product_link(stockcode, text(p.get("UrlFriendlyName"))),
        "barcode": text(p.get("Barcode")),
        "brand": text(p.get("Brand")),
        "variety": text(p.get("Variety")),
        "package_size": text(p.get("PackageSize")),
        "unit_weight_grams": to_int(p.get("UnitWeightInGrams")) or None,
        "image": text(p.get("LargeImageFile")) or text(p.get("MediumImageFile")),
        "thumbnail": text(p.get("SmallImageFile")),
        "is_new": bool_or_none(p.get("IsNew")),
        "is_online_only": bool_or_none(p.get("IsOnlineOnly")),
        "is_sponsored": bool_or_none(p.get("IsSponsoredAd")),
        "is_marketplace_item": bool_or_none(p.get("IsMarketProduct")),
        "is_bundle": bool_or_none(p.get("IsBundle")),
        "is_age_restricted": bool_or_none(p.get("AgeRestricted")),
        "is_tobacco": bool_or_none(p.get("IsTobacco")),
        "is_giftable": bool_or_none(p.get("IsGiftable")),
        "has_variants": bool_or_none(p.get("HasVariants")),
        "has_substitutes": bool_or_none(p.get("HasProductSubs")),
        "rating": rating_block,
        "pricing": pricing(p),
        "in_store_pricing": in_store_pricing(p),
        "promotion": promotion(p),
        "availability": availability(p),
        "dietary": dietary(attrs),
        "categories": categories(attrs),
        "seller": seller(p, attrs),
    }


def products(tiles, ratings=None):
    """A list of tiles -> products, skipping the empty shells."""
    ratings = ratings or {}
    out = []
    for tile in tiles or []:
        if is_real_product(tile):
            out.append(product(tile, ratings.get(str(tile.get("Stockcode")))))
    return out


def bundle_tiles(bundles):
    """Search `Products` / browse `Bundles`: [{Products: [tile, ...], Name,
    DisplayName}] -> the flat tile list (a group holds the variants the
    site stacks on one card)."""
    out = []
    for bundle in bundles or []:
        if not isinstance(bundle, dict):
            continue
        for tile in bundle.get("Products") or []:
            if isinstance(tile, dict):
                out.append(tile)
    return out


def stockcodes(tiles):
    return [str(t["Stockcode"]) for t in tiles if isinstance(t, dict) and t.get("Stockcode") is not None]


# ---- nutrition --------------------------------------------------------------------

_PER_SERVING = "Quantity Per Serving"
_PER_100 = "Quantity Per 100g / 100mL"
_NIP_RE = re.compile(r"^(.*?) Quantity Per (100g|Serve) - Total - NIP$")
# Attribute-table nutrient prefix -> the name the nutrition panel prints, so
# the two sources merge instead of duplicating.
_NIP_NAMES = {
    "Carbohydrate": "Carbohydrate", "Dietary Fibre": "Dietary Fibre", "Energy kJ": "Energy",
    "Fat Saturated": "Saturated", "Fat Total": "Fat, Total", "Protein": "Protein",
    "Sodium": "Sodium", "Sugars": "Sugars",
}


def quantity(value):
    """'730.0kJ' -> {amount: 730.0, unit: 'kJ', qualifier: None};
    '< 1.0g' -> {amount: 1.0, unit: 'g', qualifier: '<'}. None when absent."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return {"amount": float(value), "unit": None, "qualifier": None}
    match = _QUANTITY_RE.match(str(value))
    if not match:
        raw = text(str(value))
        return {"amount": None, "unit": raw, "qualifier": None} if raw else None
    return {"amount": to_float(match.group(2).replace(",", ".")), "unit": text(match.group(3)),
            "qualifier": match.group(1)}


def nutrition(detail):
    """The nutrition information panel:

        {serving_size, servings_per_pack,
         nutrients: [{name, is_sub_nutrient, per_serving, per_100}]}

    `per_100` is per 100 g or 100 mL (the pack's own basis). Rows come from
    the panel the site renders, plus any extra nutrients only present in the
    attribute table (potassium, mono / polyunsaturated fat ...)."""
    rows = detail.get("NutritionalInformation") if isinstance(detail, dict) else None
    attrs = detail.get("AdditionalAttributes") if isinstance(detail, dict) and isinstance(
        detail.get("AdditionalAttributes"), dict) else {}
    nutrients, seen = [], set()
    serving_size = servings = None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        raw_name = text(row.get("Name")) or ""
        name = raw_name.lstrip("–-— ").strip()
        if not name:
            continue
        values = row.get("Values") if isinstance(row.get("Values"), dict) else {}
        nutrients.append({
            "name": name,
            "is_sub_nutrient": raw_name[:1] in "–-—",
            "per_serving": quantity(values.get(_PER_SERVING)),
            "per_100": quantity(values.get(_PER_100)),
        })
        seen.add(name.lower())
        serving_size = serving_size or text(row.get("ServingSize"))
        servings = servings if servings is not None else to_float(row.get("ServingsPerPack"))

    extras = {}
    table = json_value(attrs.get("nutritionalinformation"))
    for attribute in (table or {}).get("Attributes") or [] if isinstance(table, dict) else []:
        if not isinstance(attribute, dict):
            continue
        match = _NIP_RE.match(text(attribute.get("Name")) or "")
        if not match:
            continue
        name = _NIP_NAMES.get(match.group(1), match.group(1))
        if name.lower() in seen:
            continue
        slot = extras.setdefault(name, {"name": name, "is_sub_nutrient": False,
                                        "per_serving": None, "per_100": None})
        slot["per_100" if match.group(2) == "100g" else "per_serving"] = quantity(attribute.get("Value"))
    nutrients.extend(extras.values())

    serving_size = serving_size or text(attrs.get("servingsize-total-nip"))
    if servings is None:
        servings = to_float(attrs.get("servingsperpack-total-nip"))
    if not nutrients and not serving_size:
        return None
    return {"serving_size": serving_size, "servings_per_pack": servings, "nutrients": nutrients}


# ---- product details -------------------------------------------------------------

def _country_of_origin(detail, attrs):
    label = detail.get("CountryOfOriginLabel") if isinstance(detail.get("CountryOfOriginLabel"), dict) else {}
    block = {
        "country": text(label.get("CountryOfOrigin")),
        "statement": text(label.get("AltText")) or text(attrs.get("countryoforigin")),
        "local_ingredient_percentage": to_float(label.get("IngredientPercentage")),
        "label_image": text(label.get("SvgImageFile")) or text(label.get("PngImageFile")),
        "disclaimer": text(label.get("Disclaimer")),
    }
    return block if any(v is not None for v in block.values()) else None


def _dimensions(attrs):
    block = {"height_mm": to_float(attrs.get("productheightmm")),
             "width_mm": to_float(attrs.get("productwidthmm")),
             "depth_mm": to_float(attrs.get("productdepthmm"))}
    return block if any(v is not None for v in block.values()) else None


def _primary_category(detail):
    raw = detail.get("PrimaryCategory") if isinstance(detail.get("PrimaryCategory"), dict) else None
    if not raw:
        return None
    return {"department": text(raw.get("Department")), "aisle": text(raw.get("Aisle"))}


def _warnings(detail, attrs):
    tga = detail.get("TgaAttributes") if isinstance(detail.get("TgaAttributes"), dict) else {}
    out = []
    for value in (tga.get("ProductWarnings"), attrs.get("tgawarning"), attrs.get("tgawarnings"),
                  attrs.get("importantinformation")):
        cleaned = clean_html(value)
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def product_details(detail, rating_block=None):
    """The product/detail answer -> the shared product shape plus the
    long-form blocks."""
    p = detail.get("Product") if isinstance(detail.get("Product"), dict) else {}
    attrs = detail.get("AdditionalAttributes") if isinstance(detail.get("AdditionalAttributes"), dict) else _attrs(p)
    tga = detail.get("TgaAttributes") if isinstance(detail.get("TgaAttributes"), dict) else {}
    out = product(dict(p, AdditionalAttributes=attrs), rating_block)

    images = [link for link in detail.get("DetailsImagePaths") or [] if text(link)]
    description = clean_html(attrs.get("description")) or clean_html(p.get("RichDescription"))
    out.update({
        "description": description,
        "short_description": text(attrs.get("ml_enriched_product_description")),
        "ingredients": clean_html(attrs.get("ingredients")),
        "claims": clean_html(attrs.get("claims")) or clean_html(attrs.get("wool_dietaryclaim")),
        "nutrition": nutrition(detail),
        "country_of_origin": _country_of_origin(detail, attrs),
        "storage_instructions": clean_html(tga.get("StorageInstructions")) or clean_html(attrs.get("storageinstructions")),
        "usage_instructions": clean_html(tga.get("Directions")) or clean_html(attrs.get("usageinstructions")),
        "suitable_for": clean_html(tga.get("SuitableFor")) or clean_html(attrs.get("suitablefor")),
        "warnings": _warnings(detail, attrs),
        "health_warning_link": text(attrs.get("tgahealthwarninglink")),
        "active_constituents": clean_html(attrs.get("activeconstituents")),
        "contents": clean_html(attrs.get("contains")) or clean_html(attrs.get("boxedcontents")),
        "manufacturer": text(attrs.get("manufacturer")),
        "packaging": clean_html(attrs.get("wool_productpackaging")),
        "recycling_information": clean_html(attrs.get("recyclableinformation")),
        "disclaimer": clean_html(attrs.get("friendlydisclaimer")),
        "colour": text(attrs.get("colour")),
        "fragrance": text(attrs.get("fragrance")),
        "features": features(attrs),
        "dimensions": _dimensions(attrs),
        "primary_category": _primary_category(detail),
        "images": images or ([out["image"]] if out.get("image") else []),
        "video_link": text(detail.get("VideoUrl")),
        "variants": market_variants(attrs),
        "delivery": market_delivery(p, attrs),
    })
    return out


# ---- search facets ------------------------------------------------------------------

_FACET_KEYS = {"Level1Categories": "categories", "Brand": "brands", "Allergens": "allergens",
               "Lifestyle": "dietary", "Healthstar": "health_star_ratings", "Vendor": "sellers"}


def filters(aggregations):
    """The result set's facets: what each filter param can be narrowed to,
    with result counts. Category rows carry the id the `category` param
    takes."""
    out = {name: [] for name in _FACET_KEYS.values()}
    for agg in aggregations or []:
        if not isinstance(agg, dict):
            continue
        key = _FACET_KEYS.get(agg.get("Name"))
        if not key:
            continue
        rows = list(agg.get("Results") or [])
        for group in agg.get("ResultsGrouped") or []:
            if isinstance(group, dict):
                rows.extend(group.get("Filters") or [])
        for row in rows:
            if not isinstance(row, dict) or not text(row.get("Term")):
                continue
            extra = row.get("ExtraOutputFields") if isinstance(row.get("ExtraOutputFields"), dict) else {}
            if key == "categories":
                out[key].append({"id": text(row.get("Term")), "name": text(extra.get("description")),
                                 "count": to_int(row.get("Count"))})
            elif key == "health_star_ratings":
                out[key].append({"value": to_float(row.get("Term")), "count": to_int(row.get("Count"))})
            else:
                out[key].append({"name": text(row.get("Name")) or text(row.get("Term")),
                                 "count": to_int(row.get("Count"))})
    return out


# ---- categories ---------------------------------------------------------------------

def category(node, slugs, depth=None):
    """One category tree node -> {id, name, slug, link, level, is_special,
    is_restricted, children}. `slugs` is the slug path to this node;
    `depth` limits how many child levels are expanded (None = all)."""
    children = [c for c in node.get("Children") or [] if isinstance(c, dict)]
    out = {
        "id": text(node.get("NodeId")),
        "name": text(node.get("Description")),
        "slug": text(node.get("UrlFriendlyName")),
        "link": refs.category_link(slugs),
        "level": to_int(node.get("NodeLevel")),
        "is_special": bool_or_none(node.get("IsSpecial")),
        "is_restricted": bool_or_none(node.get("IsRestricted")),
        "children_count": len(children),
    }
    if depth is None or depth > 0:
        next_depth = None if depth is None else depth - 1
        out["children"] = [category(c, slugs + [text(c.get("UrlFriendlyName"))], next_depth) for c in children]
    else:
        out["children"] = []
    return out


def category_ref(node, slugs):
    return {"id": text(node.get("NodeId")), "name": text(node.get("Description")),
            "slug": text(node.get("UrlFriendlyName")), "link": refs.category_link(slugs),
            "level": to_int(node.get("NodeLevel")), "is_special": bool_or_none(node.get("IsSpecial"))}


# ---- stores -------------------------------------------------------------------------

def _clock(hours, minutes):
    return f"{hours}:{minutes}"


def trading_hours(rows):
    """[{Day: 'Today', OpenHour: '8:00 AM - 8:00 PM', TradingHourForDisplay:
    'Mon: 0800-2000'}] -> [{day, opens_at, closes_at, is_closed, is_today}]
    (24 h local store time). The upstream list starts today and runs eight
    days, so the last row is the same weekday next week."""
    out = []
    for index, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        display = text(row.get("TradingHourForDisplay")) or ""
        match = _HOURS_RE.match(display)
        label = text(row.get("Day"))
        day = _DAYS.get(display[:3].lower()) or (label.lower() if label and label.lower() in _DAYS.values() else None)
        hours_text = text(row.get("OpenHour"))
        out.append({
            "day": day,
            "opens_at": _clock(match.group(2), match.group(3)) if match else None,
            "closes_at": _clock(match.group(4), match.group(5)) if match else None,
            "hours_text": hours_text,
            "is_closed": (not match) if (hours_text or display) else None,
            "is_today": index == 0 and (label or "").lower() == "today",
        })
    return out


def _partner_link(value):
    link = text(value)
    return link.split("?")[0] if link else None


def store(raw, include_partners=False):
    """A store locator row -> {id, name, division, ...}. `distance_km` is
    from the searched point (null on a direct lookup)."""
    out = {
        "id": text(str(raw.get("StoreNo"))) if raw.get("StoreNo") is not None else None,
        "name": text(raw.get("Name")),
        "division": (text(raw.get("Division")) or "").lower() or None,
        "link": _partner_link(raw.get("PartnerUrl")),
        "phone": text(raw.get("Phone")),
        "is_open": bool_or_none(raw.get("IsOpen")),
        "distance_km": to_float(raw.get("Distance")),
        "address": {
            "line1": text(raw.get("AddressLine1")),
            "line2": text(raw.get("AddressLine2")),
            "suburb": text(raw.get("Suburb")),
            "state": text(raw.get("State")),
            "postcode": text(raw.get("Postcode")),
            "country": "AU",
            "latitude": to_float(raw.get("Latitude")),
            "longitude": to_float(raw.get("Longitude")),
        },
        "utc_offset": utc_offset(raw.get("GMTZone")),
        "facilities": [f for f in (text(x) for x in raw.get("Facilities") or []) if f],
        "trading_hours": trading_hours(raw.get("TradingHours")),
    }
    if include_partners:
        out["nearby_partners"] = [store(p) for p in raw.get("NearbyPartners") or [] if isinstance(p, dict)]
    return out


def suburb(raw):
    return {
        "name": text(raw.get("SuburbName")),
        "state": text(raw.get("State")),
        "postcode": text(raw.get("PostCode")),
        "label": text(raw.get("SuburbStateString")),
        "latitude": to_float(raw.get("Latitude")),
        "longitude": to_float(raw.get("Longitude")),
    }


def pickup_location(raw):
    """A Pick up / Direct to Boot point. `id` is the address id the site's
    own fulfilment selector uses; `store_id` the store that packs the order."""
    return {
        "id": to_int(raw.get("AddressId")),
        "name": text(raw.get("Description")),
        "store_id": text(str(raw.get("FulfilmentStoreId"))) if raw.get("FulfilmentStoreId") is not None else None,
        "fulfilment_method": text(raw.get("FulfilmentMethod")),
        "delivery_methods": [m for m in (text(x) for x in raw.get("FulfilmentDeliveryMethods") or []) if m],
        "distance_km": to_float(raw.get("Distance")),
        "address": {
            "text": text(raw.get("AddressText")),
            "line1": text(raw.get("Street1")),
            "line2": text(raw.get("Street2")),
            "suburb": text(raw.get("Suburb")),
            "postcode": text(raw.get("Postcode")),
            "country": "AU",
        },
    }
