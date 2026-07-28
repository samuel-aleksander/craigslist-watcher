"""Berkeley class enrollment watcher.

Watches classes.berkeley.edu pages for waitlist/seat openings. The live
enrollment counts are embedded in each page as a Drupal JSON settings blob,
so a plain GET is enough — no JavaScript rendering.

All triggers are edge-triggered: state stores whether each condition was
already open last run, and a notification fires only on the transition into
"open". On the very first run (no state) the current reality is recorded
silently. Every successful fetch also appends a row to a CSV log so the
actual SIS refresh cadence can be measured (Berkeley doesn't document it).
"""

import csv
import dataclasses
import datetime
import json
import os
import re
import subprocess
import sys
from typing import Callable, Dict, List, Optional, Tuple

from sources import USER_AGENT, FETCH_TIMEOUT

CLASSES = [
    {
        "name": "COMPSCI 294-286",
        "url": "https://classes.berkeley.edu/content/2026-fall-compsci-294-286-lec-286",
        "watch_seat": False,
    },
    {
        "name": "COMPSCI 294-320",
        "url": "https://classes.berkeley.edu/content/2026-fall-compsci-294-320-lec-320",
        "watch_seat": False,
    },
    {
        "name": "INFO 271B",
        "url": "https://classes.berkeley.edu/content/2026-fall-info-271b-001-lec-001",
        "watch_seat": True,
    },
]

SETTINGS_RE = re.compile(
    r'data-drupal-selector="drupal-settings-json">(.*?)</script>', re.S
)


class FetchError(Exception):
    pass


@dataclasses.dataclass
class Page:
    status_code: int
    text: str


def _fetch(url: str) -> Page:
    """Fetch via curl. classes.berkeley.edu's CDN 403-blocks Python's TLS
    fingerprint (requests/urllib) while accepting curl, so we shell out."""
    try:
        proc = subprocess.run(
            [
                "curl", "-s", "-A", USER_AGENT,
                "--max-time", str(FETCH_TIMEOUT),
                "-w", "\n%{http_code}",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=FETCH_TIMEOUT + 5,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise FetchError(str(exc))
    if proc.returncode != 0:
        raise FetchError(f"curl exit {proc.returncode}")
    body, _, code = proc.stdout.rpartition("\n")
    if not code.isdigit():
        raise FetchError("no status code from curl")
    return Page(status_code=int(code), text=body)


def extract_enrollment(html: str) -> Optional[dict]:
    """Pull the enrollmentStatus dict out of the page, or None if absent."""
    m = SETTINGS_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))["ucb"]["enrollment"]["available"][
            "enrollmentStatus"
        ]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def check(
    topic: str,
    state: Optional[Dict],
    fetch: Callable[[str], Page] = _fetch,
) -> Tuple[List[dict], Dict, List[list], bool]:
    """Check every watched class.

    Returns (notifications, new_state, log_rows, ok). A class whose page
    can't be fetched/parsed keeps its previous state and flips ok to False;
    the other classes still proceed.
    """
    state = state or {}
    new_state: Dict = {}
    notifications: List[dict] = []
    log_rows: List[list] = []
    ok = True
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    for cls in CLASSES:
        name = cls["name"]
        prev = state.get(name, {})
        try:
            resp = fetch(cls["url"])
        except FetchError as exc:
            print(f"berkeley: {name}: fetch error: {exc}", file=sys.stderr)
            new_state[name] = prev
            ok = False
            continue

        # A vanished page most likely means the section was cancelled.
        if resp.status_code == 404:
            new_state[name] = {**prev, "gone": True}
            if not prev.get("gone"):
                notifications.append(
                    {
                        "topic": topic,
                        "title": "Berkeley watcher",
                        "message": f"{name}: class page is gone — section cancelled? "
                        "Remove it from berkeley.py.",
                        "click": cls["url"],
                    }
                )
            continue
        if resp.status_code != 200:
            print(f"berkeley: {name}: HTTP {resp.status_code}", file=sys.stderr)
            new_state[name] = prev
            ok = False
            continue

        status = extract_enrollment(resp.text)
        if status is None:
            print(f"berkeley: {name}: no enrollment JSON in page", file=sys.stderr)
            new_state[name] = prev
            ok = False
            continue

        enrolled = status["enrolledCount"]
        max_enroll = status["maxEnroll"]
        waitlisted = status["waitlistedCount"]
        max_waitlist = status["maxWaitlist"]
        wl_open = waitlisted < max_waitlist
        seat_open = enrolled < max_enroll

        # prev defaults to True so a missing state (first run) seeds silently.
        if wl_open and not prev.get("wl_open", True):
            notifications.append(
                {
                    "topic": topic,
                    "title": f"{name}: waitlist spot open",
                    "message": f"{name}: waitlist {waitlisted}/{max_waitlist} "
                    f"(enrolled {enrolled}/{max_enroll})",
                    "click": cls["url"],
                    "priority": "high",
                }
            )
        if cls["watch_seat"] and seat_open and not prev.get("seat_open", True):
            notifications.append(
                {
                    "topic": topic,
                    "title": f"{name}: seat open",
                    "message": f"{name}: seat open! {enrolled}/{max_enroll} enrolled, "
                    f"waitlist {waitlisted}/{max_waitlist}",
                    "click": cls["url"],
                    "priority": "high",
                }
            )

        new_state[name] = {
            "wl_open": wl_open,
            "seat_open": seat_open,
            "gone": False,
        }
        log_rows.append([now, name, enrolled, max_enroll, waitlisted, max_waitlist])

    return notifications, new_state, log_rows, ok


def append_log(path: str, rows: List[list]) -> None:
    if not rows:
        return
    write_header = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(
                ["utc", "class", "enrolled", "max_enroll", "waitlisted", "max_waitlist"]
            )
        writer.writerows(rows)
