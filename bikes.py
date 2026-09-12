"""Bike-only entry point; the car and Berkeley workflow stays disabled."""
import os
import sys
from sources import Source, parse_craigslist
from watcher import run_craigslist

BIKE_SOURCES = [
    Source("gravel", "https://www.craigslist.org/search/city/hayward-ca?cat=bia&lat=37.6356&lon=-122.1762&max_price=800&min_price=250&query=gravel&radius=39&sort=date", parse_craigslist),
    Source("road", "https://www.craigslist.org/search/city/san-mateo-ca?cat=bia&lat=37.5986&lon=-122.1954&max_price=800&min_price=250&query=road&radius=39&sort=date", parse_craigslist),
]

def main():
    topic = os.environ.get("NTFY_TOPIC_CL")
    if not topic:
        print("config error: NTFY_TOPIC_CL must be set", file=sys.stderr)
        return 2
    return 0 if run_craigslist(topic, sources=BIKE_SOURCES,
                              state_file="bikes_seen.json",
                              title="New bike on Craigslist") else 1

if __name__ == "__main__":
    sys.exit(main())
