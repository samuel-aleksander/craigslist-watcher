# Handoff: Craigslist new-listing watcher bot

## Goal

Build a lightweight bot that polls one Craigslist search URL every 15 minutes, detects listings it hasn't seen before, and pushes each new listing to the user's phone via ntfy.sh. Runs for free on GitHub Actions. No servers, no paid services.

## Decisions already made with the user (do not re-litigate)

- **Source:** Craigslist only. Facebook Marketplace was considered and explicitly rejected (login wall, ban risk, Playwright maintenance burden). However, structure the code so fetchers are pluggable — a `sources` list where each entry fetches and parses one site, all feeding a shared diff-and-notify core — so other sites can be added later.
- **Notification channel:** ntfy.sh, public topic with a random suffix. Proposed topic: `cl-crv-seattle-7km3qx9f` (confirm or regenerate at build time; user subscribes in the ntfy phone app).
- **Runner:** GitHub Actions scheduled workflow, `*/15 * * * *` cron. User accepts that GitHub cron is best-effort (runs may be delayed 3–15 min).
- **State:** a `seen.json` file committed back to the repo by the workflow after each run. This doubles as repo activity, preventing GitHub's 60-day auto-disable of scheduled workflows.
- **Notification content:** listing title + price as the message, listing URL as the click-through link (ntfy `Click` header).
- **Language:** Python 3, stdlib + `requests` + `beautifulsoup4` only.

## The watched URL (verified working 2026-07-18)

```
https://www.craigslist.org/search/area/seattle?cat=sss&max_price=10000&min_price=2000&purveyor=owner&query=cr-v&sort=date&lang=es&cc=mx
```

Use it verbatim (drop only the `#search=...` fragment — it's client-side). Verified facts from a real fetch:

- Returns HTTP 200 with server-rendered static results when fetched with a normal browser `User-Agent` — **no JavaScript rendering needed.**
- Listings are `<li class="cl-static-search-result">` elements, ~10 per page. Each contains an `<a href>` (listing URL), a `title` attribute, and a `<div class="price">`.
- Sample parsed row: `https://www.craigslist.org/view/d/tenino-2007-honda-cr-lx-sport-utility-4d/3ihywN1uggRY1tK9wFi5Lc | 2007 Honda CR-V · LX Sport Utility 4D | $5,995`
- **Dedupe key:** the opaque token at the end of the listing URL path (e.g. `3ihywN1uggRY1tK9wFi5Lc`). Craigslist no longer uses numeric posting IDs in these URLs.
- The page is in Spanish (`lang=es&cc=mx` from the user's locale). Harmless; do not "fix" it.
- Note: `cat=sss` is all-for-sale, not cars-only. With the $2,000–10,000 price band this is acceptable; mention to the user post-build that switching to the cars category (`cat=cta`) would exclude any stray parts/accessories listings.

## Repo layout

```
craigslist-watcher/
  watcher.py              # the whole bot
  sources.py              # pluggable source definitions (start with the one Craigslist source)
  seen.json               # state: known listing keys (committed by CI)
  requirements.txt        # requests, beautifulsoup4
  .github/workflows/watch.yml
  README.md               # setup: ntfy subscription steps, how to change the search URL
```

## Behavior requirements

1. **Fetch** the URL with a desktop-browser User-Agent, 30 s timeout.
2. **Parse** all `li.cl-static-search-result` items → `(key, title, price, url)`.
3. **Guard against blocks:** if zero items parse, or HTTP status ≠ 200, exit non-zero *without writing state* — a blocked/captcha page must not wipe the seen-list. Make the workflow tolerate this (a failed run is fine; do not spam the user about it).
4. **Diff** against `seen.json`. First run (no `seen.json` or empty): seed state silently, send nothing.
5. **Notify** each new listing: `POST https://ntfy.sh/<topic>` with body `"{title} — {price}"`, headers `Title: New CR-V on Craigslist` and `Click: {listing_url}`. One POST per listing.
6. **Persist:** merged key set written to `seen.json`. Prune entries older than 60 days if you add timestamps (optional; a plain ever-growing set is acceptable at this volume).
7. **Workflow:** checkout → setup-python → pip install → run script → if `seen.json` changed, commit and push with a bot identity. Grant `contents: write` permission. Also add `workflow_dispatch:` for manual test runs.

## Known risk (already discussed with user)

Craigslist sometimes 403-blocks datacenter IPs, including GitHub's Azure runners. If runs consistently fail the zero-items guard, the agreed fallback is running the same script locally on the user's Mac via launchd. Don't build the fallback now; just keep `watcher.py` runner-agnostic (all config via env vars with sane defaults: `CL_URL`, `NTFY_TOPIC`, `STATE_FILE`).

## Verification before handing back

1. Run `watcher.py` locally: first run seeds `seen.json` with ~10 keys, sends no notifications.
2. Delete one key from `seen.json`, run again: exactly one ntfy POST fires (verify with `curl https://ntfy.sh/<topic>/json?poll=1` or by subscribing in a browser tab at `https://ntfy.sh/<topic>`).
3. Simulate a block (point `CL_URL` at a page with no results): script exits non-zero, `seen.json` untouched.
4. Push repo, trigger the workflow manually via `workflow_dispatch`, confirm it runs green and commits state.
5. Tell the user the ntfy topic name and remind them to subscribe to it in the ntfy app.

## Needs from the user (only at the end)

- A GitHub repo to push to (create `craigslist-watcher` under their account with `gh repo create`, ask public vs private — public = unmetered Actions minutes, but the search URL and seen listings are then visible; private = counts against 2,000 free min/month, ~1,450 projected).
- Subscribe to the ntfy topic on their phone.
