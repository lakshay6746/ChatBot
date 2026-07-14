import json
import re
from threading import local
from typing import Optional


# Keep the matching listings available to the Flask route that initiated the
# Gemini tool call, so it can return structured cards to the browser.
_search_state = local()

STATIC_IMAGES = (
    "/static/first.jpg",
    "/static/Second.jpg",
    "/static/Third.jpg",
    "/static/Fourth.jpg",
    "/static/Fifth.jpg",
    "/static/Sixth.jpg",
    "/static/Seventh.jpg",
    "/static/Eighth.jpg",
    "/static/Nineth.jpg",
)


def add_valid_image_urls(properties: list[dict]) -> list[dict]:
    """Attach an image URL that Flask can actually serve for every listing."""
    results = []
    for property_data in properties:
        listing = property_data.copy()
        listing["image"] = STATIC_IMAGES[(int(listing["id"]) - 1) % len(STATIC_IMAGES)]
        results.append(listing)
    return results


def location_matches(listing_location: str, requested_location: str) -> bool:
    """Match location words regardless of punctuation or connector words."""
    ignored_words = {"in", "at", "the", "near", "property", "properties"}
    requested_words = [
        word for word in re.findall(r"[a-z0-9]+", requested_location.casefold())
        if word not in ignored_words
    ]
    listing_words = set(re.findall(r"[a-z0-9]+", listing_location.casefold()))
    return bool(requested_words) and all(word in listing_words for word in requested_words)


def begin_property_search() -> None:
    _search_state.results = []


def get_last_property_results() -> list[dict]:
    return getattr(_search_state, "results", [])


def search_properties_from_message(message: str, limit: int = 6) -> list[dict]:
    """Find listings when the user mentions a known city or area directly."""
    with open("property.json", "r") as file:
        properties = json.load(file)

    query = message.casefold()

    # Users commonly say only "in sector 14" rather than a full value such as
    # "Sector 14, Hyderabad". Match that sector phrase against every listing.
    sector = re.search(r"\bsector\s+\d+\b", query)
    if sector:
        sector_name = sector.group()
        return add_valid_image_urls([
            p for p in properties
            if sector_name in p["location"].casefold()
        ][:limit])

    locations = {p["location"] for p in properties} | {p["city"] for p in properties}
    matches = [
        location for location in locations
        if re.search(rf"(?<!\\w){re.escape(location.casefold())}(?!\\w)", query)
    ]

    if not matches:
        return []

    # Prefer the most specific location, e.g. "Sector 18, Hyderabad" over
    # the broader "Hyderabad".
    location = max(matches, key=len)
    return add_valid_image_urls([
        p for p in properties
        if location.casefold() in (p["location"] + " " + p["city"]).casefold()
    ][:limit])


def search_properties(
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    max_price: Optional[int] = None,
    bedrooms: Optional[int] = None,
) -> list[dict]:
    """
    Search available property listings, optionally filtered by location,
    property type, maximum price, and number of bedrooms.

    Args:
        location: City or area to search in, e.g. "Jaipur". Case-insensitive
            substring match against each listing's location.
        property_type: Type of property, e.g. "apartment", "villa", "plot".
        max_price: Maximum price in rupees. Listings above this are excluded.
        bedrooms: Exact number of bedrooms required.

    Returns:
        A list of matching property listings, each a dict with keys such as
        location, type, price, and bedrooms.
    """
    with open("property.json", "r") as file:
        properties = json.load(file)

    results = []

    for p in properties:

        if location:
            if not location_matches(p["location"], location):
                continue

        if property_type:
            if property_type.lower() != p["type"].lower():
                continue
        if max_price:
            if p["price"] > max_price:
                continue

        if bedrooms:
            if p["bedrooms"] != bedrooms:
                continue

        results.append(p)

    results = add_valid_image_urls(results)
    _search_state.results = results
    return results
