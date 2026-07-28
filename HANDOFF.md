# Handoff: web watcher bot (Craigslist listings + Berkeley waitlist)

## Goal

Build a lightweight bot that polls two watched pages every 15 minutes and pushes alerts to the user's phone via ntfy.sh. Runs for free on GitHub Actions. No servers, no paid services. Two sources, one shared poll/diff/notify core:

1. **Craigslist:** new listings on a saved car search → one notification per new listing.
2. **Berkeley class page:** notify when a waitlist spot opens for COMPSCI 294-286.

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

## Source 2: Berkeley class watcher — 3 classes (verified working 2026-07-27)

One source implementation, configured with a list of watched classes. All three URLs verified to parse identically:

| Class | URL | Watch for | State at verification |
|---|---|---|---|
| COMPSCI 294-286 | `https://classes.berkeley.edu/content/2026-fall-compsci-294-286-lec-286` | waitlist spot opens | Open, 22/35 enrolled, waitlist 10/10 |
| COMPSCI 294-320 | `https://classes.berkeley.edu/content/2026-fall-compsci-294-320-lec-320` | waitlist spot opens | Closed, 32/32 enrolled, waitlist 15/15 |
| INFO 271B-001 | `https://classes.berkeley.edu/content/2026-fall-info-271b-001-lec-001` | seat opens AND waitlist spot opens | Closed, 49/49 enrolled, waitlist 30/30 |

Verified facts from real fetches:

- Plain GET with a browser User-Agent returns HTTP 200 static HTML (~24 KB). **No JavaScript needed.**
- Live enrollment data is embedded as JSON in `<script type="application/json" data-drupal-selector="drupal-settings-json">`. Parse that blob; the numbers live at `ucb.enrollment.available.enrollmentStatus`: `enrolledCount`, `maxEnroll`, `waitlistedCount`, `maxWaitlist`, `status.code` ("O" open / "C" closed). (There is a parallel `ucb.enrollment.history` block — use `available`.)

**Triggers (confirmed with user), all edge-triggered** — keep last-seen counts per class in state, notify only on the transition into the "open" condition (and again if it closes and re-opens), never on every run while the condition holds:

- **Waitlist spot opens** (all 3 classes): `waitlistedCount < maxWaitlist`. Message: `"{class}: waitlist open {waitlistedCount}/{maxWaitlist} (enrolled {enrolledCount}/{maxEnroll})"`.
- **Seat opens** (INFO 271B only): `enrolledCount < maxEnroll`. Message: `"{class}: seat open! {enrolledCount}/{maxEnroll} enrolled"`. Caveat to mention to the user post-build: with a 30-person waitlist, a freed seat is normally auto-filled from the waitlist, so this alert may be rare/brief — the waitlist alert is the actionable one.

All alerts are time-sensitive → ntfy priority `high`, `Click:` set to the class page URL.

Use a **single separate ntfy topic** for all Berkeley classes, distinct from the Craigslist topic, so the user can set a louder alert sound for it; the message text identifies the class.

**Unknown: how often the underlying enrollment feed refreshes.** The page itself re-renders on a 15-minute CDN cache (`cache-control: max-age=900`, fresh `last-modified` observed), but Berkeley does not document how often SIS pushes new enrollment counts to classes.berkeley.edu — it may be near-real-time or a daily batch. To measure it: append `(timestamp, class, enrolledCount, waitlistedCount)` to a small `berkeley_log.csv` in the repo on every run for the first two weeks. After a few days the log shows the actual update cadence; tell the user what it is, and if it turns out to be a daily batch, note that alert latency is bounded by Berkeley's refresh, not our polling (no code change needed — the Berkeley check rides along at zero extra cost).

Same block-guard rule as Craigslist, applied per class: if a class page's JSON blob is missing or unparseable, skip that class without touching its state (other classes proceed normally). Two of the three classes are already status "C"/Closed — that's the normal full state, NOT an alert condition. Only send a one-time informational notification if a section is cancelled/deleted (page 404s or the section disappears), so the user knows to stop watching it.

## Repo layout

```
craigslist-watcher/
  watcher.py              # shared poll/diff/notify core
  sources.py              # pluggable source definitions (craigslist + berkeley_waitlist)
  state.json              # per-source state: {"craigslist": {...seen keys...}, "berkeley": {...last counts...}} (committed by CI)
  requirements.txt        # requests, beautifulsoup4
  .github/workflows/watch.yml
  README.md               # setup: ntfy subscription steps, how to change the watched URLs
```

Each source is an object/dict with a `fetch_and_check(state) -> (notifications, new_state)` contract; the core runs every source, sends the notifications, and persists state only for sources that succeeded (one blocked source must not lose the other's state or stop its notifications).

## Behavior requirements

1. **Fetch** the URL with a desktop-browser User-Agent, 30 s timeout.
2. **Parse** all `li.cl-static-search-result` items → `(key, title, price, url)`.
3. **Guard against blocks:** if zero items parse, or HTTP status ≠ 200, exit non-zero *without writing state* — a blocked/captcha page must not wipe the seen-list. Make the workflow tolerate this (a failed run is fine; do not spam the user about it).
4. **Diff** against `seen.json`. First run (no `seen.json` or empty): seed state silently, send nothing.
5. **Notify** each new listing: `POST https://ntfy.sh/<topic>` with body `"{title} — {price}"`, headers `Title: New CR-V on Craigslist` and `Click: {listing_url}`. One POST per listing.
6. **Persist:** merged key set written to `seen.json`. Prune entries older than 60 days if you add timestamps (optional; a plain ever-growing set is acceptable at this volume).
7. **Workflow:** checkout → setup-python → pip install → run script → if state changed, commit and push with a bot identity. Grant `contents: write` permission. Also add `workflow_dispatch:` for manual test runs.
8. **Secrets (repo is PUBLIC):** the ntfy topic names are the only secret — anyone who knows a topic can subscribe to or spam it. Pass them as GitHub Actions repo secrets (`NTFY_TOPIC_CL`, `NTFY_TOPIC_BERKELEY`), never commit them, and make the script fail loudly if they're unset. Everything else (search URL, state, log) is fine in the open.

## Known risk (already discussed with user)

Craigslist sometimes 403-blocks datacenter IPs, including GitHub's Azure runners. If runs consistently fail the zero-items guard, the agreed fallback is running the same script locally on the user's Mac via launchd. Don't build the fallback now; just keep `watcher.py` runner-agnostic (all config via env vars with sane defaults: `CL_URL`, `NTFY_TOPIC`, `STATE_FILE`).

## Verification before handing back

1. Run `watcher.py` locally: first run seeds `seen.json` with ~10 keys, sends no notifications.
2. Delete one key from `seen.json`, run again: exactly one ntfy POST fires (verify with `curl https://ntfy.sh/<topic>/json?poll=1` or by subscribing in a browser tab at `https://ntfy.sh/<topic>`).
3. Simulate a block (point `CL_URL` at a page with no results): script exits non-zero, `seen.json` untouched.
4. Berkeley source: run once to seed state for all 3 classes (all waitlists currently full, no notifications expected). Then hand-edit one class's stored counts to simulate a spot opening and confirm the notification fires exactly once, with high priority, names the right class, and does not repeat on the next run. Repeat for the INFO 271B seat-open trigger.
5. Push repo, trigger the workflow manually via `workflow_dispatch`, confirm it runs green and commits state.
6. Tell the user both ntfy topic names and remind them to subscribe to both in the ntfy app.

## Needs from the user (only at the end)

- A GitHub repo to push to (create `craigslist-watcher` under their account with `gh repo create`). **Billing constraint (verified):** GitHub bills private-repo Actions per job, rounded UP to the whole minute, so a 15-min cron = ~2,920 billed minutes/month, which EXCEEDS the 2,000 free minutes. Either use a **public repo** (standard runners are free/unmetered — recommended; downside is the search URL and state are world-readable) or a **private repo at a 30-min cron** (~1,460 min/month, fits). User has chosen: **public repo, 15-minute cron**.
- Subscribe to the ntfy topic on their phone.
