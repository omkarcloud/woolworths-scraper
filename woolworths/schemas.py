"""Marshmallow request schemas for every /woolworths/* route. Generic fields
come from the shared schema_fields.py; this module adds the Woolworths
resolvers. Every schema's load() output is the kwargs dict its endpoint
function takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    product    a stockcode (888140) OR a woolworths.com.au product link
    products   comma-separated stockcodes and/or links (max 20)
    category   a category id (1_DEB537E), a slug path (bakery/packaged-bread-bakery)
               OR a woolworths.com.au browse link
    store      a store number (8964) OR a woolworths.com.au store link
    location   a postcode (2000), "latitude,longitude" OR a suburb name (Bondi)
"""
import re

from marshmallow import ValidationError, validate

from schema_fields import (BaseSchema, ChoiceField, CommaListField, Flag, LimitField, PageField,
                           PositiveInt, QueryField, RefField, StrippedString)
from woolworths import refs

# public sort value -> the API's SortType
SORTS = {
    "relevance": "TraderRelevance",
    "price_asc": "PriceAsc",
    "price_desc": "PriceDesc",
    "unit_price_asc": "CUPAsc",
    "unit_price_desc": "CUPDesc",
    "name_asc": "Name",
    "name_desc": "NameDesc",
    "newest": "AvailableDateDesc",
}
REVIEW_SORTS = {"latest": "LATEST", "highest_rating": "HIGHEST_RATING", "lowest_rating": "LOWEST_RATING"}
DIVISIONS = {"supermarkets": "SUPERMARKETS", "bws": "BWS", "petrol": "PETROL",
             "all": "SUPERMARKETS,PETROL,BWS"}

# public filter value -> the facet term the site filters on (validated
# 2026-10-05 against the Allergens / Lifestyle facets of a broad search)
ALLERGENS = {
    "crustacea_free": "Crustacea Free", "dairy_free": "Dairy Free", "egg_free": "Egg Free",
    "fish_free": "Fish Free", "gluten_free": "Gluten Free", "lactose_free": "Lactose Free",
    "no_artificial_colours_or_flavours": "No Artificial Colours or Flavours",
    "no_artificial_preservatives": "No Artificial Preservatives", "peanut_free": "Peanut Free",
    "sesame_free": "Sesame Free", "soy_free": "Soy Free", "tree_nut_free": "Tree Nut Free",
    "wheat_free": "Wheat Free",
}
DIETARY = {
    "gluten_free": "Gluten Free", "halal": "Halal", "high_fibre": "High Fibre",
    "high_protein": "High Protein", "kosher": "Kosher", "low_fat": "Low Fat", "low_salt": "Low Salt",
    "low_saturated_fat": "Low Saturated Fat", "low_sugar": "Low Sugar", "no_caffeine": "No Caffeine",
    "organic": "Organic", "source_of_fibre": "Source of Fibre", "source_of_protein": "Source of Protein",
    "vegan": "Vegan", "vegetarian": "Vegetarian", "wholegrain": "Wholegrain",
}
HEALTH_STARS = ["0.5", "1", "1.5", "2", "2.5", "3", "3.5", "4", "4.5", "5"]
_SPECIALS_TYPE_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


# ---- id-or-link fields -------------------------------------------------------------

class ProductField(RefField):
    resolver = staticmethod(refs.resolve_product)


class ProductListField(RefField):
    resolver = staticmethod(refs.resolve_products)


class CategoryField(RefField):
    resolver = staticmethod(refs.resolve_category)


class StoreField(RefField):
    resolver = staticmethod(refs.resolve_store)


class LocationField(RefField):
    resolver = staticmethod(refs.resolve_location)


class BarcodeField(RefField):
    resolver = staticmethod(refs.resolve_barcode)


class PostcodeField(RefField):
    resolver = staticmethod(refs.resolve_postcode)


class SpecialsTypeField(StrippedString):
    """half_price / half-price / "Half Price" -> half_price. The set of
    shelves changes with the weekly catalogue, so the value is checked
    against the live tree by the endpoint (/woolworths/specials/types)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", "half_price")
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return "half_price"
        value = re.sub(r"[\s\-]+", "_", value.lower())
        if not _SPECIALS_TYPE_RE.match(value):
            raise ValidationError("Must be a specials type such as half_price (see /woolworths/specials/types).")
        return value


def _sort(default="relevance"):
    return ChoiceField(SORTS, load_default=SORTS[default])


def _brands():
    return CommaListField(upper=False, max_items=10)


def _allergens():
    return CommaListField(value_map=ALLERGENS, max_items=len(ALLERGENS))


def _dietary():
    return CommaListField(value_map=DIETARY, max_items=len(DIETARY))


def _health_stars():
    return CommaListField(allowed=HEALTH_STARS, max_items=len(HEALTH_STARS))


# ---- schemas ---------------------------------------------------------------------------

class EmptySchema(BaseSchema):
    pass


class ProductSchema(BaseSchema):
    product = ProductField()


class ProductsSchema(BaseSchema):
    products = ProductListField()


class BarcodeSchema(BaseSchema):
    barcode = BarcodeField()


class SearchSchema(BaseSchema):
    query = QueryField(max_length=100)
    page = PageField(max_page=500)
    sort = _sort()
    category = CategoryField(required=False, load_default=None)
    brands = _brands()
    allergens = _allergens()
    dietary = _dietary()
    health_star_ratings = _health_stars()
    sellers = _brands()
    specials_only = Flag()


class AutocompleteSchema(BaseSchema):
    query = QueryField(max_length=100, validate=validate.Length(min=2, max=100))


class ReviewsSchema(ProductSchema):
    sort = ChoiceField(REVIEW_SORTS, load_default=REVIEW_SORTS["latest"])
    page = PageField(max_page=1000)
    limit = LimitField(default=10, max_size=50)


class StockSchema(ProductSchema):
    location = LocationField()
    in_stock_only = Flag()
    limit = LimitField(default=10, max_size=50)


class NewProductsSchema(BaseSchema):
    page = PageField(max_page=500)
    sort = _sort("newest")
    brands = _brands()
    allergens = _allergens()
    dietary = _dietary()
    health_star_ratings = _health_stars()


class CategoryTreeSchema(BaseSchema):
    category = CategoryField(required=False, load_default=None)
    depth = PositiveInt(max_value=5, load_default=2)


class CategoryProductsSchema(BaseSchema):
    category = CategoryField()
    page = PageField(max_page=500)
    sort = _sort()
    brands = _brands()
    allergens = _allergens()
    dietary = _dietary()
    health_star_ratings = _health_stars()
    specials_only = Flag()


class SpecialsSchema(BaseSchema):
    type = SpecialsTypeField()
    page = PageField(max_page=500)
    sort = _sort()
    brands = _brands()
    allergens = _allergens()
    dietary = _dietary()
    health_star_ratings = _health_stars()


class StoreSearchSchema(BaseSchema):
    location = LocationField()
    division = ChoiceField(DIVISIONS, load_default=DIVISIONS["supermarkets"])
    limit = LimitField(default=10, max_size=50)


class StoreSchema(BaseSchema):
    store = StoreField()
    division = ChoiceField({k: v for k, v in DIVISIONS.items() if k != "all"},
                           load_default=DIVISIONS["supermarkets"])


class PickupLocationsSchema(BaseSchema):
    postcode = PostcodeField()


class LocationSearchSchema(BaseSchema):
    query = QueryField(max_length=60, validate=validate.Length(min=3, max=60))
