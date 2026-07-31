from flask import Flask, render_template, request, jsonify, session
from google import genai
from google.genai import types
from dotenv import load_dotenv
from difflib import get_close_matches
import json
import os
import re
from threading import Lock
from uuid import uuid4

from tool import (
    begin_property_search,
    get_last_nearby_results,
    get_last_property_results,
    get_supported_locations,
    extract_max_price,
    search_properties,
    search_properties_from_message,
)

# -----------------------------
# Load API Key
# -----------------------------
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise Exception("GEMINI_API_KEY not found in .env")

# -----------------------------
# Gemini Client
# -----------------------------
client = genai.Client(api_key=api_key)

SYSTEM_INSTRUCTION = """
You are Lakshay AI.

If someone asks:
- Who made you?
- Who created you?
- Who developed you?

Always reply exactly:

"I was created by Lakshay Khatri."

For any property related question,
ALWAYS use the search_properties tool.

Extract every stated requirement before calling the tool. In particular,
convert Indian budgets such as "4 Cr" to rupees (40000000) and pass a
request such as "possession by 2031" as possession_by=2031. Also handle
related date wording such as "till 2031", "until 2031", "future projects",
"upcoming projects", "ready by 2028", and similar possession-timeline
questions. If the tool returns no matches, explain that there are no exact
matches in the current listing data and ask whether the user would like to
broaden the location, budget, or possession date.

Never make up property data.
"""

# -----------------------------
# Flask
# -----------------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-development-secret")

# Keep the active Gemini conversation and latest cards separate for each
# browser session. A single global chat would mix different users' history.
_conversation_chats = {}
_conversation_results = {}
_conversation_pending_searches = {}
_conversation_lock = Lock()


def conversation_id() -> str:
    if "conversation_id" not in session:
        session["conversation_id"] = uuid4().hex
    return session["conversation_id"]


def chat_for_conversation(conversation: str):
    with _conversation_lock:
        if conversation not in _conversation_chats:
            _conversation_chats[conversation] = client.chats.create(
                model="gemini-2.5-flash",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=[search_properties],
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True,
                    ),
                ),
            )
        return _conversation_chats[conversation]


def sort_follow_up_results(properties: list[dict], message: str) -> list[dict]:
    """Handle simple follow-ups such as 'most affordable' using prior cards."""
    query = message.casefold()
    requested_count = re.search(r"\b(?:top|first|only)\s+(\d+)\b", query)
    limit = min(max(int(requested_count.group(1)), 1), 12) if requested_count else None
    if any(term in query for term in ("affordable", "lowest", "low to high", "cheapest")):
        properties = sorted(properties, key=lambda listing: int(listing.get("price") or 0))
    elif any(term in query for term in ("highest price", "high to low", "most expensive")):
        properties = sorted(properties, key=lambda listing: int(listing.get("price") or 0), reverse=True)
    elif any(term in query for term in ("best", "top", "highest rated")):
        properties = sorted(properties, key=lambda listing: float(listing.get("rating") or 0), reverse=True)
    return properties[:limit] if limit else properties


def is_result_follow_up(message: str) -> bool:
    query = message.casefold()
    return any(term in query for term in (
        "affordable", "cheapest", "lowest", "low to high", "high to low",
        "most expensive", "best", "top", "highest rated", "show me",
    ))


def has_explicit_location(message: str) -> bool:
    """True when the user has supplied a location that must not be replaced by old results."""
    return bool(re.search(r"\b(?:in|near|at)\s+[^\s]", message, flags=re.IGNORECASE))


PROPERTY_INTENT_TERMS = (
    "property", "properties", "apartment", "villa", "flat", "plot",
    "home", "house", "project", "projects", "real estate", "builder",
    "bedroom", "bhk", "possession", "amenities", "locality", "location",
    "budget", "investment",
)

COMMON_LOCATION_TERMS = (
    "delhi", "noida", "gurugram", "faridabad", "ghaziabad", "mumbai",
    "pune", "bengaluru", "bangalore", "hyderabad", "chennai", "jaipur",
    "kolkata", "ahmedabad", "chandigarh", "indore", "lucknow", "kochi",
)


def correct_property_typos(message: str) -> str:
    """Correct close misspellings only for property terms and common cities."""
    correction_terms = PROPERTY_INTENT_TERMS + COMMON_LOCATION_TERMS

    def replace_word(match: re.Match) -> str:
        word = match.group(0)
        if len(word) < 4:
            return word
        # 0.66 accepts common omitted-letter typos such as "prtuery" while
        # still limiting corrections to the small real-estate vocabulary.
        match_candidates = get_close_matches(word.casefold(), correction_terms, n=1, cutoff=0.66)
        return match_candidates[0] if match_candidates else word

    return re.sub(r"[A-Za-z]+", replace_word, message)


def is_property_query(message: str) -> bool:
    query = message.casefold()
    # Do not treat unrelated or inappropriate phrases as a real-estate search
    # merely because they contain a word such as "property".
    off_topic_terms = (
        "girl", "girls", "boy", "boys", "dating", "date", "girlfriend",
        "boyfriend", "joke", "weather", "recipe", "movie", "song",
    )
    if any(re.search(rf"\b{re.escape(term)}\b", query) for term in off_topic_terms):
        return False

    if any(word in query for word in PROPERTY_INTENT_TERMS):
        return True

    # A message containing one of the catalogue's supported locations is also
    # a property-search request, even when the user only types a city name.
    return any(location.casefold() in query for location in get_supported_locations())


def has_supported_location(message: str) -> bool:
    """Return whether a message contains a city or locality in the catalogue."""
    query = message.casefold()
    return any(
        re.search(rf"(?<!\w){re.escape(location.casefold())}(?!\w)", query)
        for location in get_supported_locations()
    )


def reply_for_results(reply: str, properties: list[dict], nearby_results: list[dict]) -> str:
    """Avoid showing the model's negative fallback text when the app already has real cards to show."""
    text = (reply or "").strip()
    if not text:
        return "Here are the properties I found for you."

    if properties or nearby_results:
        negative_phrases = (
            "no exact match",
            "don't have properties",
            "do not have properties",
            "couldn't find",
            "could not find",
            "there are no exact",
            "no properties",
            "i don't have",
            "i do not have",
        )
        if any(phrase in text.casefold() for phrase in negative_phrases):
            return "Here are the matching properties I found for you."

    return text


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/projects", methods=["GET"])
def projects():
    """Return project names for the deep-dive project picker."""
    with open("property.json", "r", encoding="utf-8") as file:
        listings = json.load(file)
    project_names = sorted({listing.get("title", "").strip() for listing in listings if listing.get("title")})
    return jsonify({"projects": project_names})


def build_property_reply(user_message: str, properties: list[dict], nearby_results: list[dict]) -> str:
    """Create a deterministic property reply that matches the catalogue results."""
    if properties:
        return f"I found {len(properties)} matching property option(s) for your request."

    if nearby_results:
        return "I found a few nearby options you can compare."

    supported_locations = ", ".join(get_supported_locations()[:40])
    return (
        "I can help with properties in these supported locations: "
        f"{supported_locations}. Which city or locality would you like me to search in?"
    )


def selected_project_matches(message: str) -> list[dict]:
    """Return the exact catalogue listing chosen in the project picker."""
    match = re.fullmatch(r"\s*Tell me about the project\s+(.+?)\s*", message, flags=re.IGNORECASE)
    if not match:
        return []

    project_name = match.group(1).casefold()
    with open("property.json", "r", encoding="utf-8") as file:
        listings = json.load(file)
    return [listing for listing in listings if listing.get("title", "").casefold() == project_name]


@app.route("/chat", methods=["POST"])
def chatbot():

    data = request.get_json()

    print("\n==============================")
    print("Incoming Request:")
    print(data)
    print("==============================\n")

    user_message = data["message"]
    conversation = conversation_id()

    print("User Message:")
    print(user_message)
    print()

    # Validate before searching. A normal property search is collected in two
    # steps: location first, then budget. Cards are shown only after both are
    # available. Project-picker requests remain an exception because they name
    # one exact project for a detail view.
    search_message = correct_property_typos(user_message)
    property_question = is_property_query(search_message)
    ready_to_search = False
    intake_reply = None
    next_step = None

    with _conversation_lock:
        pending_search = _conversation_pending_searches.get(conversation)

    if pending_search:
        property_question = True
        if pending_search["awaiting"] == "location":
            search_message = f'{pending_search["query"]} in {search_message}'
            if has_supported_location(search_message):
                if extract_max_price(search_message):
                    ready_to_search = True
                    with _conversation_lock:
                        _conversation_pending_searches.pop(conversation, None)
                else:
                    with _conversation_lock:
                        _conversation_pending_searches[conversation] = {
                            "query": search_message, "awaiting": "budget"
                        }
                    intake_reply = "Great. What is your maximum budget? For example, ₹80 lakh or 2 Cr."
                    next_step = "budget"
            else:
                intake_reply = "Please enter a supported city or locality, such as Delhi, Mumbai, Bengaluru, or Hyderabad."
                next_step = "location"
        else:
            search_message = f'{pending_search["query"]} under {search_message}'
            if extract_max_price(search_message):
                ready_to_search = True
                with _conversation_lock:
                    _conversation_pending_searches.pop(conversation, None)
            else:
                intake_reply = "Please enter your maximum budget, for example ₹80 lakh or 2 Cr."
                next_step = "budget"
    elif property_question:
        project_matches = selected_project_matches(search_message)
        if project_matches:
            ready_to_search = True
        elif not has_supported_location(search_message):
            with _conversation_lock:
                _conversation_pending_searches[conversation] = {
                    "query": search_message, "awaiting": "location"
                }
            intake_reply = "Which city or locality are you looking in?"
            next_step = "location"
        elif not extract_max_price(search_message):
            with _conversation_lock:
                _conversation_pending_searches[conversation] = {
                    "query": search_message, "awaiting": "budget"
                }
            intake_reply = "What is your maximum budget? For example, ₹80 lakh or 2 Cr."
            next_step = "budget"
        else:
            ready_to_search = True

    begin_property_search()
    direct_matches = (
        selected_project_matches(search_message) or search_properties_from_message(search_message)
        if ready_to_search else []
    )
    properties = get_last_property_results() or direct_matches

    if property_question and ready_to_search and not properties and is_result_follow_up(search_message) and not has_explicit_location(search_message):
        with _conversation_lock:
            previous_results = _conversation_results.get(conversation, [])
        properties = sort_follow_up_results(previous_results, search_message)

    if property_question and ready_to_search and properties:
        properties = sort_follow_up_results(properties, search_message)
        with _conversation_lock:
            _conversation_results[conversation] = properties

    nearby_results = get_last_nearby_results()

    if intake_reply:
        reply = intake_reply
    elif property_question:
        reply = build_property_reply(search_message, properties, nearby_results)
    else:
        reply = (
            "I can help only with property-related questions, such as finding homes, "
            "comparing projects, budgets, locations, or amenities. What property are you looking for?"
        )

    # The UI should receive the direct and nearby listings separately.
    if nearby_results:
        nearby_locations = ", ".join({item.get("city", "nearby area") for item in nearby_results if item.get("city")})
        reply = (
            f"{reply}\n\nI also found a few nearby options in {nearby_locations} so you can compare "
            "similar properties in neighboring areas."
        )

    return jsonify({
        "reply": reply,
        "properties": properties,
        "nearby_properties": nearby_results,
        "next_step": next_step,
    })


if __name__ == "__main__":
    app.run(debug=True)
