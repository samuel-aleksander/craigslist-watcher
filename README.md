# watcher

A tiny bot that runs every ~15 minutes on GitHub Actions and pushes alerts
to a phone via [ntfy.sh](https://ntfy.sh). No servers, no paid services.
It watches two kinds of things:

1. **Craigslist** — one saved car search; every never-before-seen listing
   becomes a push notification (title + price, tap to open the listing).
2. **Berkeley classes** — enrollment pages on classes.berkeley.edu; a push
   fires when a waitlist spot (or, where configured, a seat) opens up.

## How it works

- `watcher.py` is the core: it runs each source, sends notifications, and
  persists per-source state. A failure in one source never touches the
  other's state.
- `sources.py` parses Craigslist search pages and diffs against `seen.json`.
- `berkeley.py` reads the enrollment JSON embedded in each class page and
  edge-triggers on "waitlist/seat just opened". It also appends every
  reading to `berkeley_log.csv` to measure how often Berkeley actually
  refreshes the numbers (undocumented).
- State files are committed back to the repo after every run — which also
  keeps the scheduled workflow from being auto-disabled for inactivity.
- A blocked/captcha/unparseable page can never wipe state: that source is
  skipped and retried next run.

## Notifications

The ntfy topic names are **secrets** (anyone who knows a topic name can
subscribe to it or spam it — so they are not committed anywhere in this
repo). They live in two GitHub Actions repo secrets:

- `NTFY_TOPIC_CL` — Craigslist alerts
- `NTFY_TOPIC_BERKELEY` — Berkeley alerts (sent at high priority)

To receive them: install the ntfy app
([iOS](https://apps.apple.com/app/ntfy/id1625396347) /
[Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy))
and subscribe to both topic names.

## Configuration

Watched things are defined in code:

- The Craigslist search URL: `DEFAULT_CL_URL` in [`sources.py`](sources.py)
  (or override with `CL_URL`). Build a new URL on Craigslist and drop the
  trailing `#search=...` fragment. Note: `cat=sss` is *all for sale*; switch
  to `cat=cta` (cars & trucks) to exclude stray parts/accessories listings.
- The class list: `CLASSES` in [`berkeley.py`](berkeley.py) — each entry has
  a name, the classes.berkeley.edu URL, and `watch_seat` for whether to also
  alert on open seats (waitlist openings are always watched).
- More listing sites: add a `Source` with its own `parse` function to
  `default_sources()` in [`sources.py`](sources.py).

## Running locally

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
set -a; source .env.local; set +a   # provides the two NTFY_TOPIC_* vars
.venv/bin/python watcher.py
```

The first run seeds state and sends nothing. Later runs notify on changes.
Exit codes: `0` clean, `1` a source had trouble (state kept, run tolerated
by CI), `2` missing required env vars.

## Automation

[`.github/workflows/watch.yml`](.github/workflows/watch.yml) runs the script
every 15 minutes (`*/15 * * * *`, best-effort — GitHub may delay runs a few
minutes) and commits state when it changes. Trigger a manual run any time
from the **Actions → watch → Run workflow** button (`workflow_dispatch`).

If a site starts consistently blocking GitHub's runners, the fallback is to
run the same script on a Mac via `launchd` — no code changes needed, just
set the env vars.
