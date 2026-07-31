"""Run deterministic checks against the recommendation golden dataset."""
import json
from pathlib import Path

from tool import search_properties


def matches(listing: dict, query: dict, criterion: str) -> bool:
    if criterion == "location":
        return query["location"].casefold() in f'{listing["location"]} {listing["city"]}'.casefold()
    if criterion == "property_name":
        return query["property_name"].casefold() in f'{listing["title"]} {listing["builder"]}'.casefold()
    if criterion == "max_price":
        return listing["price"] <= query["max_price"]
    if criterion == "property_type":
        return listing["type"].casefold() == query["property_type"].casefold()
    if criterion == "possession_by":
        return int(listing["possession"]) <= query["possession_by"]
    return listing[criterion] == query[criterion]


def main() -> int:
    cases = json.loads(Path("evals/golden_recommendations.json").read_text(encoding="utf-8"))
    failures = []
    for case in cases:
        query, expected = case["query"], case["expect"]
        results = search_properties(**query)
        valid = len(results) >= expected["minimum_results"] and all(
            matches(listing, query, criterion)
            for listing in results
            for criterion in expected["all_match"]
        )
        print(f'{"PASS" if valid else "FAIL"}: {case["id"]} ({len(results)} results)')
        if not valid:
            failures.append(case["id"])
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
