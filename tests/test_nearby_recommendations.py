from tool import get_last_nearby_results, get_supported_locations, search_properties_from_message


def test_delhi_search_returns_nearby_recommendations():
    results = search_properties_from_message("Suggest property in Delhi", limit=3)

    assert results, "expected direct Delhi matches"
    nearby = get_last_nearby_results()
    assert nearby, "expected nearby recommendations for Delhi"
    nearby_cities = {property_data["city"].casefold() for property_data in nearby}
    assert any(city in nearby_cities for city in {"noida", "gurugram", "faridabad", "ghaziabad"})


def test_future_project_date_queries_filter_by_year():
    results = search_properties_from_message("Show me future projects till 2027", limit=10)

    assert results, "expected date-based future-project matches"
    assert all(int(property_data["possession"]) <= 2027 for property_data in results), (
        "expected possession year to be filtered by the requested date"
    )


def test_bedroom_queries_filter_by_bhk():
    results = search_properties_from_message("Show me 3 bhk apartments in Hyderabad", limit=10)

    assert results, "expected bedroom-based matches"
    assert all(int(property_data["bedrooms"]) == 3 for property_data in results), (
        "expected bedroom count to be filtered for BHK requests"
    )


def test_bangalore_alias_matches_bengaluru_catalogue():
    results = search_properties_from_message("Show me properties in Bangalore", limit=5)

    assert results, "expected Bangalore alias queries to return catalogue results"
    assert all(property_data["city"].casefold() == "bengaluru" for property_data in results), (
        "expected Bangalore alias to resolve to Bengaluru catalogue records"
    )


def test_supported_locations_include_major_cities():
    locations = get_supported_locations()

    assert locations, "expected a supported-locations list"
    assert "bengaluru" in locations
    assert "chennai" in locations
    assert "delhi" in locations


def test_supported_locations_include_locality_names():
    locations = get_supported_locations()

    assert "sector 1, ahmedabad" in locations
    assert "sector 102, dwarka expressway, gurugram" in locations
