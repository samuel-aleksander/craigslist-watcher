#!/usr/bin/env python3
"""Craigslist + Berkeley watcher.

Two independent checks per run, sharing one poll/diff/notify core:
  1. Craigslist: new listings on a saved search -> one push per listing.
  2. Berkeley: waitlist/seat openings on watched classes (see berkeley.py).

A failure in one source never blocks the other or touches the other's state.

Runner-agnostic: everything is configured via env vars so the same script
runs on GitHub Actions or locally on a Mac (launchd).

Env vars:
  NTFY_TOPIC_CL        ntfy.sh topic for Craigslist alerts (REQUIRED)
  NTFY_TOPIC_BERKELEY  ntfy.sh topic for Berkeley alerts (REQUIRED)
  CL_URL               Craigslist search URL (see sources.py default)
  STATE_FILE           Craigslist seen-list JSON (default: seen.json)
  BERKELEY_STATE_FILE  Berkeley state JSON (default: berkeley_state.json)
  BERKELEY_LOG         cadence-measurement CSV (default: berkeley_log.csv)

Exit codes:
  0  ran cleanly
  1  a source had trouble (blocked/unparseable) — its state left untouched,
     other sources ran normally
  2  configuration error (missing required env var)
"""

import json
import os
import sys
from typing import List, Optional, Set

import requests

import berkeley
from sources import Listing, SourceBlocked, default_sources

NTFY_TITLE_CL = "New CR-V on Craigslist"
NTFY_TIMEOUT = 30


def load_json(path: str):
    """Return parsed JSON state, or None if there is no usable state yet."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    return data or None


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def notify(topic: str, title: str, message: str, click: str, priority: str = None):
    headers = {"Title": title, "Click": click}
    if priority:
        headers["Priority"] = priority
    resp = requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers=headers,
        timeout=NTFY_TIMEOUT,
    )
    resp.raise_for_status()


def run_craigslist(topic: str) -> bool:
    """Diff listing sources against the seen-list. Returns False on trouble."""
    state_file = os.environ.get("STATE_FILE", "seen.json")
    known: Optional[Set[str]] = None
    raw = load_json(state_file)
    if raw is not None:
        known = set(raw)
    first_run = known is None
    known = known or set()

    all_listings: List[Listing] = []
    for source in default_sources():
        try:
            listings = source.fetch()
        except SourceBlocked as exc:
            print(f"blocked: {exc}; state untouched", file=sys.stderr)
            return False
        except requests.RequestException as exc:
            print(f"fetch error: {source.name}: {exc}; state untouched", file=sys.stderr)
            return False
        print(f"{source.name}: parsed {len(listings)} listings")
        all_listings.extend(listings)

    seen_now: Set[str] = set()
    unique: List[Listing] = []
    for listing in all_listings:
        if listing.key not in seen_now:
            seen_now.add(listing.key)
            unique.append(listing)

    merged = known | seen_now

    if first_run:
        save_json(state_file, sorted(merged))
        print(f"craigslist first run: seeded {len(merged)} keys, sent nothing")
        return True

    new_listings = [l for l in unique if l.key not in known]
    sent = 0
    for listing in new_listings:
        body = f"{listing.title} — {listing.price}".strip(" —")
        try:
            notify(topic, NTFY_TITLE_CL, body, listing.url)
            sent += 1
            print(f"notified: {body} | {listing.url}")
        except requests.RequestException as exc:
            # Don't record the key as seen, so the next run retries it.
            print(f"notify failed for {listing.key}: {exc}", file=sys.stderr)
            merged.discard(listing.key)

    save_json(state_file, sorted(merged))
    print(f"craigslist: sent {sent}/{len(new_listings)} notifications")
    return True


def run_berkeley(topic: str) -> bool:
    state_file = os.environ.get("BERKELEY_STATE_FILE", "berkeley_state.json")
    log_file = os.environ.get("BERKELEY_LOG", "berkeley_log.csv")

    state = load_json(state_file)
    notifications, new_state, log_rows, ok = berkeley.check(topic, state)

    sent = 0
    for n in notifications:
        try:
            notify(**n)
            sent += 1
            print(f"notified: {n['message']}")
        except requests.RequestException as exc:
            # Re-arm the trigger: restore the class's previous state so the
            # next run sees the transition again and retries this alert.
            print(f"notify failed ({n['title']}): {exc}", file=sys.stderr)
            failed_class = n["title"].split(":")[0]
            if failed_class in new_state:
                new_state[failed_class] = (state or {}).get(failed_class, {})

    save_json(state_file, new_state)
    berkeley.append_log(log_file, log_rows)
    print(f"berkeley: checked {len(log_rows)} classes, sent {sent} notifications")
    return ok


def main() -> int:
    topic_cl = os.environ.get("NTFY_TOPIC_CL")
    topic_berkeley = os.environ.get("NTFY_TOPIC_BERKELEY")
    if not topic_cl or not topic_berkeley:
        print(
            "config error: NTFY_TOPIC_CL and NTFY_TOPIC_BERKELEY must be set "
            "(GitHub Actions: repo secrets; local: source .env.local)",
            file=sys.stderr,
        )
        return 2

    ok = run_craigslist(topic_cl)
    ok = run_berkeley(topic_berkeley) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
