"""/woolworths/stores/*, /woolworths/locations/search — the store locator
(supermarkets, Metro, BWS, petrol; trading hours, facilities, coordinates),
one store by number, Pick up / Direct to Boot points and suburb lookup."""
from woolworths import parsers as P
from woolworths import shared
from woolworths.fetch import WoolworthsBadRequest, WoolworthsNotFound, ui, v3


def search(location, division="SUPERMARKETS", limit=10):
    where, place = shared.locate(location)
    params = {"Max": limit, "Division": division, "Facility": ""}
    params.update(where)
    body = ui("/StoreLocator/Stores", params) or {}
    rows = [P.store(s) for s in body.get("Stores") or [] if isinstance(s, dict)]
    return {"location": place, "count": len(rows), "stores": rows}


def details(store, division="SUPERMARKETS"):
    try:
        raw = ui("/StoreLocator/Store", {"Division": division, "StoreNo": store})
    except WoolworthsBadRequest:
        # an unknown store number answers 400 "Sorry an error has occurred"
        raise WoolworthsNotFound(f"store '{store}' not found in {division.lower()}")
    if not isinstance(raw, dict) or not raw.get("StoreNo"):
        raise WoolworthsNotFound(f"store '{store}' not found in {division.lower()}")
    return {"store": P.store(raw, include_partners=True)}


def pickup_locations(postcode):
    rows = v3("/fulfilment/stores", {"postcode": postcode}) or []
    points = [P.pickup_location(r) for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    return {"postcode": postcode, "count": len(points), "pickup_locations": points}


def locations(query):
    rows = shared.suburbs(query)
    return {"query": query, "count": len(rows), "locations": rows}
