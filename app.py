from flask import Flask, render_template, request, jsonify
from google import genai
from google.genai import types
from dotenv import load_dotenv
import os

from tool import (
    begin_property_search,
    get_last_property_results,
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

Never make up property data.
"""

# -----------------------------
# Chat Session
# -----------------------------
chat = client.chats.create(
    model="gemini-2.5-flash",
    config=types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=[search_properties]
    )
)

# -----------------------------
# Flask
# -----------------------------
app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chatbot():

    data = request.get_json()

    print("\n==============================")
    print("Incoming Request:")
    print(data)
    print("==============================\n")

    user_message = data["message"]

    print("User Message:")
    print(user_message)
    print()

    # Preserve structured listings returned by Gemini's property-search tool.
    begin_property_search()
    direct_matches = search_properties_from_message(user_message)

    # Send message to Gemini
    response = chat.send_message(user_message)

    print("Gemini Response:")
    print(response)
    print()

    return jsonify({
        "reply": response.text,
        "properties": get_last_property_results() or direct_matches,
    })


if __name__ == "__main__":
    app.run(debug=True)
