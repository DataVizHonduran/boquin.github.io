import os, requests, json
key = os.environ["EIA_API_KEY"]

def dump(route, terms):
    url = f"https://api.eia.gov/v2/{route}/facet/series/"
    r = requests.get(url, params={"api_key": key}).json()
    facets = r.get("response", {}).get("facets", [])
    for f in facets:
        name = f.get("name", "")
        if any(t.lower() in name.lower() for t in terms):
            print(f"{route}: {f.get('id')}  ->  {name}")

dump("petroleum/pri/spt", ["gasoline"])
dump("natural-gas/pri/fut", ["henry hub"])
