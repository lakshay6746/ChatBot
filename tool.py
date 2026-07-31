import json
import re
from threading import local
from typing import Optional
from urllib.parse import quote


# Keep the matching listings available to the Flask route that initiated the
# Gemini tool call, so it can return structured cards to the browser.
_search_state = local()


def _requested_city_from_text(text: str, properties: list[dict]) -> Optional[str]:
    cities = sorted({p["city"] for p in properties}, key=len, reverse=True)
    query = text.casefold()
    for city in cities:
        if re.search(rf"(?<!\w){re.escape(city.casefold())}(?!\w)", query):
            return city
    return None


def _nearby_locations_for(city: str) -> list[str]:
    return {
        "delhi": ["Noida", "Gurugram", "Faridabad", "Ghaziabad"],
        "gurugram": ["Noida", "Delhi", "Faridabad", "Ghaziabad"],
        "noida": ["Delhi", "Gurugram", "Faridabad", "Ghaziabad"],
        "mumbai": ["Thane", "Navi Mumbai", "Pune"],
        "hyderabad": ["Secunderabad", "Gachibowli", "Miyapur"],
        "chandigarh": ["Mohali", "Panchkula"],
        "bangalore": ["Whitefield", "Electronic City", "Hebbal"],
        "chennai": ["Tambaram", "Pallavaram", "Kanchipuram"],
    }.get(city.casefold(), [])

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


def _normalise(value: object) -> str:
    """Normalise text consistently for search and sorting."""
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


_LOCATION_ALIASES = {
    "bangalore": "bengaluru",
    "bengaluru": "bengaluru",
    "new delhi": "delhi",
    "delhi ncr": "delhi",
    "bombay": "mumbai",
    "calcutta": "kolkata",
    "madras": "chennai",
    "ncr": "delhi",
}


def canonicalise_location_text(text: str) -> str:
    """Map common location aliases to the canonical place names used in the data."""
    canonical = _normalise(text)
    for alias, replacement in _LOCATION_ALIASES.items():
        canonical = re.sub(rf"\b{re.escape(alias)}\b", replacement, canonical)
    return canonical


def _rank_properties(
    properties: list[dict],
    *,
    location: Optional[str] = None,
    max_price: Optional[int] = None,
    sort_by: str = "recommended",
) -> list[dict]:
    """Return a deterministic, explainable ordering for matching listings."""
    requested_location = set(re.findall(r"[a-z0-9]+", _normalise(location)))

    def score(listing: dict) -> tuple:
        listing_location = set(re.findall(r"[a-z0-9]+", _normalise(f'{listing.get("location")} {listing.get("city")}')))
        location_score = len(requested_location & listing_location)
        rating = float(listing.get("rating") or 0)
        featured = int(bool(listing.get("featured")))
        available = int(bool(listing.get("available", True)))
        budget_fit = 0
        if max_price and max_price > 0:
            # A home nearer the stated budget is usually more useful than a
            # much cheaper, otherwise equivalent listing.
            budget_fit = -abs(max_price - int(listing.get("price") or 0)) / max_price
        return (location_score, available, featured, rating, budget_fit, -int(listing.get("id") or 0))

    if sort_by == "price_low_to_high":
        return sorted(properties, key=lambda p: (int(p.get("price") or 0), -float(p.get("rating") or 0)))
    if sort_by == "price_high_to_low":
        return sorted(properties, key=lambda p: (-int(p.get("price") or 0), -float(p.get("rating") or 0)))
    if sort_by == "rating":
        return sorted(properties, key=lambda p: (-float(p.get("rating") or 0), int(p.get("price") or 0)))
    return sorted(properties, key=score, reverse=True)


def add_valid_image_urls(properties: list[dict]) -> list[dict]:
    """Attach an image URL that Flask can actually serve for every listing."""
    results = []
    for property_data in properties:
        listing = property_data.copy()
        listing["image"] = STATIC_IMAGES[(int(listing["id"]) - 1) % len(STATIC_IMAGES)]
        results.append(listing)
    return results


def add_map_links(properties: list[dict]) -> list[dict]:
    """Attach a Google Maps link for each listing so the UI can open it quickly."""
    results = []
    for property_data in properties:
        listing = property_data.copy()
        map_query = ", ".join(
            part for part in [
                listing.get("location"),
                listing.get("city"),
                listing.get("state"),
                listing.get("country"),
            ]
            if part
        )
        listing["map_link"] = (
            f"https://www.google.com/maps/search/?api=1&query={quote(map_query)}"
            if map_query
            else ""
        )
        results.append(listing)
    return results


def nearby_locations_for(location: str) -> list[str]:
    """Return nearby metro-city suggestions for a requested location."""
    normalized = _normalise(location)
    if any(term in normalized for term in ("delhi", "new delhi")):
        return ["Noida", "Gurugram", "Faridabad", "Ghaziabad"]
    if "gurugram" in normalized:
        return ["Delhi", "Noida", "Faridabad", "Ghaziabad"]
    if "noida" in normalized:
        return ["Delhi", "Gurugram", "Faridabad", "Ghaziabad"]
    if "faridabad" in normalized:
        return ["Delhi", "Noida", "Gurugram", "Ghaziabad"]
    if "ghaziabad" in normalized:
        return ["Delhi", "Noida", "Gurugram", "Faridabad"]
    if "mumbai" in normalized:
        return ["Navi Mumbai", "Thane", "Panvel"]
    if "pune" in normalized:
        return ["Hinjewadi", "Baner", "Kharadi"]
    if "bangalore" in normalized or "bengaluru" in normalized:
        return ["Whitefield", "Electronic City", "Sarjapur"]
    if "hyderabad" in normalized:
        return ["Gachibowli", "Madhapur", "Kukatpally"]
    if "chennai" in normalized:
        return ["OMR", "Adyar", "Tambaram"]
    return []


def location_matches(listing_location: str, requested_location: str) -> bool:
    """Match location words regardless of punctuation or connector words."""
    ignored_words = {"in", "at", "the", "near", "property", "properties"}
    requested_words = [
        word for word in re.findall(r"[a-z0-9]+", canonicalise_location_text(requested_location))
        if word not in ignored_words
    ]
    listing_words = set(re.findall(r"[a-z0-9]+", canonicalise_location_text(listing_location)))
    return bool(requested_words) and all(word in listing_words for word in requested_words)


def extract_max_price(message: str) -> Optional[int]:
    """Read common Indian budget formats such as ₹4 Cr, 75 lakh, or 40000000."""
    budget = re.search(r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*(cr|crore|lakh|lac|lacs)?\b", message, re.I)
    if not budget:
        return None
    amount = float(budget.group(1))
    unit = (budget.group(2) or "").casefold()
    if unit in {"cr", "crore"}:
        return int(amount * 10_000_000)
    if unit in {"lakh", "lac", "lacs"}:
        return int(amount * 100_000)
    return int(amount) if amount >= 100_000 else None


def extract_possession_by(message: str) -> Optional[int]:
    """Extract a latest acceptable possession year from natural-language dates."""
    query = message.casefold()

    direct_patterns = [
        r"(?:possession|delivery|ready|move[- ]?in|handover|completion)\s*(?:by|before|till|until|up to|upto|in|within)?\s*(20\d{2})",
        r"(?:till|until|by|before|up to|upto)\s*(20\d{2})",
        r"(?:future|upcoming)\s+(?:project|projects|property|properties).{0,30}\b(20\d{2})",
        r"\b(?:from|between)\s*(20\d{2})\b",
    ]

    for pattern in direct_patterns:
        match = re.search(pattern, message, re.I)
        if match:
            return int(match.group(1))

    if any(term in query for term in ("future project", "future projects", "upcoming project", "upcoming projects")):
        year_matches = re.findall(r"\b(20\d{2})\b", message)
        if year_matches:
            return int(year_matches[-1])

    if any(term in query for term in ("between", "from", "to")) and "and" in query:
        year_matches = re.findall(r"\b(20\d{2})\b", message)
        if len(year_matches) >= 2:
            return int(max(year_matches))

    if any(term in query for term in ("future", "upcoming", "till", "until")) and re.search(r"\b20\d{2}\b", message):
        year_matches = re.findall(r"\b(20\d{2})\b", message)
        if year_matches:
            return int(year_matches[-1])

    return None


def extract_result_limit(message: str, default: int = 6) -> int:
    """Read requested card counts such as 'top 3' or 'show first 5'."""
    match = re.search(r"\b(?:top|first|only)\s+(\d+)\b", message, re.I)
    if not match:
        return default
    return max(1, min(int(match.group(1)), 12))


def extract_bedrooms(message: str) -> Optional[int]:
    """Read bedroom requests such as '3 bhk', 'three bedrooms', or '2 room flat'."""
    query = message.casefold()

    bhk_match = re.search(r"\b(\d+)\s*(?:bhk|bedroom|bedrooms|room|rooms)\b", query)
    if bhk_match:
        return int(bhk_match.group(1))

    number_words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    for word, value in number_words.items():
        if re.search(rf"\b{word}\b", query) and re.search(r"\b(?:bhk|bedroom|bedrooms|room|rooms)\b", query):
            return value

    return None


def rank_message_results(properties: list[dict], message: str) -> list[dict]:
    """Order direct natural-language results for common comparison requests."""
    query = message.casefold()
    if any(term in query for term in ("affordable", "cheapest", "lowest", "low to high")):
        return sorted(properties, key=lambda listing: int(listing.get("price") or 0))
    if any(term in query for term in ("expensive", "high to low")):
        return sorted(properties, key=lambda listing: int(listing.get("price") or 0), reverse=True)
    if any(term in query for term in ("best", "top", "according to you")):
        return _rank_properties(properties)
    return properties


def begin_property_search() -> None:
    _search_state.results = []
    _search_state.nearby_results = []


def get_last_property_results() -> list[dict]:
    return getattr(_search_state, "results", [])


def get_last_nearby_results() -> list[dict]:
    return getattr(_search_state, "nearby_results", [])


def get_supported_locations() -> list[str]:
    """Return the canonical city and locality names supported by the local dataset."""
    with open("property.json", "r") as file:
        properties = json.load(file)

    cities = {canonicalise_location_text(p["city"]) for p in properties}
    localities = {canonicalise_location_text(p["location"]) for p in properties}
    return sorted(cities | localities)


def search_properties_from_message(message: str, limit: int = 6) -> list[dict]:
    """Find listings when the user mentions a known city or area directly."""
    with open("property.json", "r") as file:
        properties = json.load(file)

    query = canonicalise_location_text(message.casefold())
    limit = extract_result_limit(message, limit)
    max_price = extract_max_price(message)
    possession_by = extract_possession_by(message)
    bedrooms = extract_bedrooms(message)
    property_type = next((kind for kind in ("apartment", "villa", "flat", "plot", "studio", "penthouse", "farmhouse", "duplex") if re.search(rf"\b{kind}s?\b", query)), None)

    def matches_criteria(property_data: dict) -> bool:
        return (
            (not property_type or property_data["type"].casefold() == property_type)
            and (not max_price or property_data["price"] <= max_price)
            and (not possession_by or int(property_data["possession"]) <= possession_by)
            and (not bedrooms or int(property_data["bedrooms"]) == bedrooms)
        )

    def build_result_set(candidates: list[dict], *, source: str) -> list[dict]:
        ranked = add_valid_image_urls(rank_message_results(candidates, message)[:limit])
        ranked = add_map_links(ranked)
        for item in ranked:
            item["source"] = source
        return ranked

    # Users commonly say only "in sector 14" rather than a full value such as
    # "Sector 14, Hyderabad". Match that sector phrase against every listing.
    sector = re.search(r"\bsector\s+\d+\b", query)
    if sector:
        sector_name = sector.group()
        direct_matches = build_result_set([
            p for p in properties
            if sector_name in p["location"].casefold() and matches_criteria(p)
        ], source="direct")
        requested_location = sector_name
    else:
        requested_area = re.search(
            r"\b(?:in|near|at)\s+(.+?)(?=\s+(?:with|under|below|budget|and\s+(?:a\s+)?(?:budget|possession)|possession)\b|$)",
            query,
        )
        if requested_area:
            area = requested_area.group(1).strip(" ,.?")
            area_results = [
                p for p in properties
                if location_matches(f'{p["location"]} {p["city"]}', area) and matches_criteria(p)
            ]
            if area_results:
                direct_matches = build_result_set(area_results, source="direct")
                requested_location = area
            else:
                direct_matches = []
                requested_location = area
        else:
            locations = {canonicalise_location_text(p["location"]) for p in properties} | {canonicalise_location_text(p["city"]) for p in properties}
            matches = [
                location for location in locations
                if re.search(rf"(?<!\\w){re.escape(location)}(?!\\w)", query)
            ]

            if not matches:
                # Broad follow-ups such as "top 3 most affordable properties" do
                # not contain a location. Return structured cards from the catalogue
                # rather than relying on the LLM to turn its prose into cards.
                broad_search = any(term in query for term in (
                    "property", "properties", "project", "projects", "top", "best", "affordable", "cheapest", "future", "upcoming",
                ))
                if broad_search:
                    candidates = [p for p in properties if matches_criteria(p)]
                    direct_matches = build_result_set(candidates, source="direct")
                    requested_location = None
                else:
                    direct_matches = []
                    requested_location = None
            else:
                # Prefer the most specific location, e.g. "Sector 18, Hyderabad" over
                # the broader "Hyderabad".
                requested_location = max(matches, key=len)
                direct_matches = build_result_set([
                    p for p in properties
                    if requested_location.casefold() in (p["location"] + " " + p["city"]).casefold() and matches_criteria(p)
                ], source="direct")

    nearby_matches = []
    if direct_matches and requested_location:
        nearby_names = nearby_locations_for(requested_location)
        if nearby_names:
            included_ids = {int(item["id"]) for item in direct_matches}
            nearby_candidates = [
                p for p in properties
                if int(p["id"]) not in included_ids
                and matches_criteria(p)
                and not location_matches(f'{p["location"]} {p["city"]}', requested_location)
                and any(location_matches(f'{p["location"]} {p["city"]}', name) for name in nearby_names)
            ]
            if nearby_candidates:
                nearby_matches = build_result_set(nearby_candidates, source="nearby")[:max(1, min(3, max(1, limit // 2)))]

    _search_state.results = direct_matches
    _search_state.nearby_results = nearby_matches
    return direct_matches


def search_properties(
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    property_name: Optional[str] = None,
    max_price: Optional[int] = None,
    bedrooms: Optional[int] = None,
    possession_by: Optional[int] = None,
    sort_by: str = "recommended",
    limit: int = 6,
) -> list[dict]:
    """
    Search available property listings, optionally filtered by location,
    property type, maximum price, and number of bedrooms.

    Args:
        location: City or area to search in, e.g. "Jaipur". Case-insensitive
            substring match against each listing's location.
        property_type: Type of property, e.g. "apartment", "villa", "plot".
        property_name: Full or partial property/project name, e.g. "Lodha".
        max_price: Maximum price in rupees. Listings above this are excluded.
        bedrooms: Exact number of bedrooms required.
        possession_by: Latest acceptable possession year, e.g. 2031.
        sort_by: One of "recommended" (default), "price_low_to_high",
            "price_high_to_low", or "rating".
        limit: Maximum number of listings to return. Defaults to six cards.

    Returns:
        A list of matching property listings, each a dict with keys such as
        location, type, price, and bedrooms.
    """
    with open("property.json", "r") as file:
        properties = json.load(file)

    valid_sorts = {"recommended", "price_low_to_high", "price_high_to_low", "rating"}
    sort_by = sort_by if sort_by in valid_sorts else "recommended"
    results = []

    for p in properties:

        if location:
            if not location_matches(f'{p["location"]} {p["city"]}', location):
                continue

        if property_type:
            if property_type.lower() != p["type"].lower():
                continue
        if property_name:
            searchable_name = _normalise(f'{p.get("title")} {p.get("builder")}')
            if _normalise(property_name) not in searchable_name:
                continue
        if max_price:
            if p["price"] > max_price:
                continue

        if bedrooms:
            if p["bedrooms"] != bedrooms:
                continue

        if possession_by:
            if int(p["possession"]) > possession_by:
                continue

        results.append(p)

    # Do not return every match for broad searches such as a whole city. A
    # huge response made the browser create hundreds of cards and image loads,
    # so the first images appeared blank while the page was overwhelmed.
    results = _rank_properties(results, location=location, max_price=max_price, sort_by=sort_by)
    direct_results = add_map_links(add_valid_image_urls(results[:max(1, min(limit, 12))]))

    nearby_results = []
    if location:
        nearby_names = nearby_locations_for(location)
        if nearby_names:
            included_ids = {int(item["id"]) for item in direct_results}
            nearby_candidates = [
                p for p in properties
                if int(p["id"]) not in included_ids
                and not location_matches(f'{p["location"]} {p["city"]}', location)
                and any(location_matches(f'{p["location"]} {p["city"]}', name) for name in nearby_names)
            ]
            if nearby_candidates:
                nearby_results = add_map_links(add_valid_image_urls(
                    _rank_properties(nearby_candidates, location=location, max_price=max_price, sort_by=sort_by)[:max(1, min(3, max(1, limit // 2)))]
                ))
                for item in nearby_results:
                    item["source"] = "nearby"

    final_results = []
    for item in direct_results:
        item["source"] = "direct"
        final_results.append(item)
    for item in nearby_results:
        final_results.append(item)

    _search_state.results = final_results
    _search_state.nearby_results = nearby_results
    return final_results
