#!/usr/bin/env python3
"""Craigslist new-listing watcher.

Polls one (or more) search sources, diffs against a committed state file,
and pushes each never-before-seen listing to the user's phone via ntfy.sh.

Runner-agnostic: everything is configured via env vars with sane defaults so
the same script runs on GitHub Actions or locally on a Mac (launchd).

Env vars:
  CL_URL       search URL for the Craigslist source (see sources.py default)
  NTFY_TOPIC   ntfy.sh topic to POST to (default below)
  STATE_FILE   path to the JSON seen-list (default: seen.json)

Exit codes:
  0  ran cleanly (seeded, or diffed and notified)
  1  a source looked blocked (non-200 / zero items) — state left untouched
"""

import json
import os
import sys
from typing import List, Optional, Set

import requests

from sources import Listing, SourceBlocked, default_sources

DEFAULT_TOPIC = "cl-crv-seattle-eg3t4caz"
NTFY_TITLE = "New CR-V on Craigslist"
NTFY_TIMEOUT = 30


def load_state(path: str) -> Optional[Set[str]]:
    """Return the known key set, or None if there is no usable state yet.

    None (missing / empty / unparseable file) signals a first run: the core
    seeds silently instead of notifying on everything.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    keys = set(data)
    return keys if keys else None


def save_state(path: str, keys: Set[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(keys), f, indent=2)
        f.write("\n")


def notify(topic: str, listing: Listing) -> None:
    body = f"{listing.title} — {listing.price}".strip(" —")
    resp = requests.post(
        f"https://ntfy.sh/{topic}",
        data=body.encode("utf-8"),
        headers={"Title": NTFY_TITLE, "Click": listing.url},
        timeout=NTFY_TIMEOUT,
    )
    resp.raise_for_status()


def main() -> int:
    state_file = os.environ.get("STATE_FILE", "seen.json")
    topic = os.environ.get("NTFY_TOPIC", DEFAULT_TOPIC)

    known = load_state(state_file)
    first_run = known is None
    known = known or set()

    # Gather from all sources first. If any source looks blocked, bail without
    # writing state so a captcha page can't wipe the seen-list.
    all_listings: List[Listing] = []
    for source in default_sources():
        try:
            listings = source.fetch()
        except SourceBlocked as exc:
            print(f"blocked: {exc}", file=sys.stderr)
            return 1
        except requests.RequestException as exc:
            print(f"fetch error: {source.name}: {exc}", file=sys.stderr)
            return 1
        print(f"{source.name}: parsed {len(listings)} listings")
        all_listings.extend(listings)

    # De-dupe within this run, preserving first-seen order.
    seen_now: Set[str] = set()
    unique: List[Listing] = []
    for listing in all_listings:
        if listing.key not in seen_now:
            seen_now.add(listing.key)
            unique.append(listing)

    merged = known | seen_now

    if first_run:
        save_state(state_file, merged)
        print(f"first run: seeded {len(merged)} keys, sent no notifications")
        return 0

    new_listings = [l for l in unique if l.key not in known]
    if not new_listings:
        save_state(state_file, merged)
        print("no new listings")
        return 0

    sent = 0
    for listing in new_listings:
        try:
            notify(topic, listing)
            sent += 1
            print(f"notified: {listing.title} | {listing.price} | {listing.url}")
        except requests.RequestException as exc:
            # A failed push shouldn't crash the run; but do NOT record this key
            # as seen, so the next run retries it.
            print(f"notify failed for {listing.key}: {exc}", file=sys.stderr)
            merged.discard(listing.key)

    save_state(state_file, merged)
    print(f"sent {sent}/{len(new_listings)} notifications")
    return 0


if __name__ == "__main__":
    sys.exit(main())
