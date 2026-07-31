# Property chatbot — product and engineering requirements

## Purpose

Help buyers discover, understand, shortlist, compare, and enquire about properties without inventing facts. A recommendation is successful when it meets the buyer's explicit requirements and moves them toward a shortlist, enquiry, or site visit.

## Current design

The application is a Flask web chatbot using Gemini with a local `property.json` catalogue. `tool.py` applies deterministic filters for location, type, maximum price, bedrooms, and possession year, then returns listing cards. The browser can open a details modal. Listings are currently read from JSON on each search; there is no user account, persistent state, shortlist, or comparison flow.

### Current limitations

- Natural-language fallback recognizes only a small set of constraints, while the Gemini tool can express more.
- Before this change, matching results were returned in JSON-file order instead of by relevance.
- Project/title/builder search was unavailable.
- There is no reliable way to prove recommendation quality over time.
- A shared server-side Gemini chat must not become the conversation store for different users.
- Coordinates, brochure data, unit availability, and price freshness are not currently source-validated.

## Decisions made now (P0)

### Deterministic recommendation engine

The recommendation pipeline is:

`message → extracted constraints → hard-filtered listings → deterministic rank → cards`

Hard requirements are never silently violated: explicit location, maximum price, property type, bedroom count, and possession deadline filter the catalogue. The engine now also supports partial `property_name` matching across title and builder. It ranks eligible listings by location overlap, availability, featured status, rating, and budget fit. The ordering is stable and supports `recommended`, `price_low_to_high`, `price_high_to_low`, and `rating` sorts.

The current implementation is intentionally conservative: it does not claim commute quality, investment return, or availability that the catalogue cannot prove.

### Golden-data evaluation

`evals/golden_recommendations.json` is the initial versioned golden dataset, and `evaluate_recommendations.py` runs it without a live model. Each case provides a structured query and assertions about the returned listings. This separates deterministic search quality from LLM-response quality.

Run it with:

```powershell
.\venv\Scripts\python.exe evaluate_recommendations.py
```

The initial cases cover city/type/budget constraints, project-name search, and bedrooms with possession date. Add a case whenever a production search bug is fixed.

## Evaluation plan

Grow the golden dataset to 50–100 reviewed cases. Each case should include:

- user query and structured expected filters;
- expected eligible IDs and expected top results in order;
- forbidden IDs that violate hard constraints;
- expected clarification or no-result recovery behavior;
- rationale and source-data assumptions.

Measure filter precision/recall, hard-constraint violations (target: zero), Recall@6, NDCG@6, top-1/top-3 accuracy, and no fabricated listing facts. Keep deterministic retrieval tests in normal CI. Run LLM extraction and answer-quality checks separately because they are probabilistic and may incur model cost.

## Next requirements, ordered by value

### P0 — complete recommendation quality

1. Normalize city/locality/project aliases (for example, Gurgaon/Gurugram) and return applied filters plus result count.
2. Add minimum/maximum budget, bedroom ranges, area range, availability/status, furnishing, parking, amenities, and builder filters.
3. Parse common structured values with rules (money, BHK, years, area); use LLM extraction only for ambiguous phrasing and validate the result against a schema.
4. Show why each result matches and its material tradeoff. On no exact match, offer labelled, one-constraint relaxations rather than silently breaking a budget or location requirement.
5. Diversify broad-search results across locality, builder, and type where appropriate.

### P1 — state and property understanding

1. Maintain a per-session active search and active property, isolated by user/session.
2. Ask users before saving long-term preferences; save only clear, editable preferences such as budget range, preferred localities, property type, and household needs.
3. Add a shortlist of property IDs with notes and timestamps. Comparison should allow 3–4 listings and compare price, area, price/sq.ft., possession, status, parking, amenities, nearby distances, RERA, and known tradeoffs.
4. Ground property Q&A in the active listing. Clearly separate known facts, reasoned recommendations (for example, family suitability), and unknowns.
5. Add name, builder, landmark, and alias search to the natural-language path as well as the structured tool path.

### P2 — external and document-backed answers

1. Integrate Maps only after validating coordinates and adding a reliable provider for nearby places/routes. Cite the source and make travel-time variability clear.
2. Store brochures, floor plans, and master plans with source/page references. Extract structured facts and cite the relevant page/image in answers.
3. Treat current unit inventory and pricing as a timestamped source feed; brochures alone are not authoritative for availability.

### P3 — scale and platform architecture

1. Move from JSON to a relational database when preferences, shortlists, audit history, or larger catalogue filtering require it. Index normalized city, locality, project, type, price, bedrooms, possession, and availability; use full-text search for names.
2. Store chat history per session/user with retention and deletion policy. Store structured search events separately from raw messages.
3. Consider LangGraph only once there are multiple dependable stateful tools (search, Maps, documents, inventory). It is unnecessary orchestration complexity today.

## Options and tradeoffs

| Topic | Decision | Tradeoff |
| --- | --- | --- |
| Rules vs LLM extraction | Hybrid: rules for numeric/property grammar, LLM for ambiguity | More engineering, but repeatable and testable constraints |
| Ranking | Deterministic scoring before learned ranking | Less personalized initially, but explainable and safe |
| JSON vs database | Retain JSON for the demo; migrate for saved user data/scale | JSON is simple but reloads every query and lacks indexes |
| Memory | Separate session state, saved preferences, and shortlist | More schema work, but avoids treating chat text as truth |
| Maps/documents | Defer until data provenance is validated | Delays rich answers, prevents inaccurate location/document claims |
| LangGraph | Defer | Keeps the current system simpler until workflows justify orchestration |

## Product safeguards and improvements

- Validate listing fields at import: required data, price/currency, possession format, images, RERA/contact provenance, and coordinates.
- Add `last updated` and source status to each listing.
- Add `Why this recommendation?` and `Not relevant` feedback controls; log anonymized search → open → shortlist → compare → enquiry events.
- Do not make unsupported claims about safety, demographics, guaranteed appreciation/ROI, commute time, legal status, or live availability.
- Define the first buyer segment and the success event (shortlist, call, site visit, or booking) with sales, buyers, and operations before tuning ranking weights.

## Stakeholder discussion outcomes

A product and engineering review agreed on this sequencing: deterministic search and evaluations first; then ranking explanations and no-result recovery; then session preferences, shortlist, and comparison; then grounded property Q&A; then Maps/document intelligence; finally database/indexes and provider-agnostic orchestration when usage warrants it.

Questions to settle with sales, a target buyer, and data operations:

1. Who is the first target segment, and does “best” mean lifestyle, investment, or rental yield?
2. Which listing source is authoritative, who updates it, and how fresh must price/inventory be?
3. Which fields can be shown publicly, and what is the preferred conversion action?
4. Which recommendation constraints are non-negotiable for users versus preferences that may be relaxed?
