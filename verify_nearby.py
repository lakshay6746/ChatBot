from tool import search_properties_from_message, get_last_nearby_results

results = search_properties_from_message("Suggest property in Delhi", limit=3)
print("direct count=", len(results))
nearby = get_last_nearby_results()
print("nearby count=", len(nearby))
print("nearby cities=", {item["city"] for item in nearby})
