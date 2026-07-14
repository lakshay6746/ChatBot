from tool import search_properties

print("\nSearching for properties in Mumbai...\n")

results = search_properties(location="Mumbai")

if results:
    for property in results:
        print(f"Title      : {property['title']}")
        print(f"Location   : {property['location']}")
        print(f"Price      : ₹{property['price']}")
        print(f"Bedrooms   : {property['bedrooms']}")
        print(f"Type       : {property['type']}")
        print("-" * 40)
else:
    print("No properties found.")