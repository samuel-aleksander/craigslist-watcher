# Craigslist new-listing watcher

A tiny bot that polls one Craigslist search every ~15 minutes, detects
listings it hasn't seen before, and pushes each one to your phone via
[ntfy.sh](https://ntfy.sh). Runs for free on GitHub Actions — no servers, no
paid services.

## How it works

1. `watcher.py` fetches the search URL, parses the listings, and diffs them
   against `seen.json` (a state file committed back to the repo after every
   run — which also keeps the scheduled workflow from being auto-disabled).
2. Each never-before-seen listing is POSTed to an ntfy topic.
3. On a blocked/captcha page (non-200 or zero results), it exits without
   touching `seen.json`, so a bad fetch can never wipe your history.

## Get notifications on your phone

1. Install the **ntfy** app ([iOS](https://apps.apple.com/app/ntfy/id1625396347) /
   [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)).
2. Subscribe to this topic:

   ```
   cl-crv-seattle-eg3t4caz
   ```

   The topic is a public ntfy topic with a random suffix — anyone who knows
   the exact name can read it, so it's obscure-but-not-secret. That's fine for
   Craigslist listings.

You can preview notifications in a browser at
<https://ntfy.sh/cl-crv-seattle-eg3t4caz>.

## Changing what it watches

Everything is configured with environment variables (with sane defaults), so
the script runs unmodified on GitHub Actions or locally:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CL_URL` | the CR-V search below | Craigslist search URL to poll |
| `NTFY_TOPIC` | `cl-crv-seattle-eg3t4caz` | ntfy topic to notify |
| `STATE_FILE` | `seen.json` | where the seen-list is stored |

Default search URL:

```
https://www.craigslist.org/search/area/seattle?cat=sss&max_price=10000&min_price=2000&purveyor=owner&query=cr-v&sort=date&lang=es&cc=mx
```

To change the search, build a new URL on Craigslist, drop the trailing
`#search=...` fragment, and either edit `DEFAULT_CL_URL` in
[`sources.py`](sources.py) or set `CL_URL`.

> **Note:** `cat=sss` is *all for sale*, not cars-only. With the
> $2,000–$10,000 price band that's fine in practice; switch to `cat=cta`
> (cars & trucks) if you want to exclude stray parts/accessories listings.

### Watching more sites

Sources are pluggable. Each entry in `default_sources()` in
[`sources.py`](sources.py) fetches and parses one site into a list of
`Listing(key, title, price, url)`; they all feed the shared diff-and-notify
core. Add a `Source` with its own `parse` function to watch another site.

## Running locally

```bash
pip install -r requirements.txt
python watcher.py
```

The first run seeds `seen.json` and sends nothing. Later runs notify on
anything new.

## Automation

[`.github/workflows/watch.yml`](.github/workflows/watch.yml) runs the script
every 15 minutes (`*/15 * * * *`, best-effort — GitHub may delay runs a few
minutes) and commits `seen.json` when it changes. Trigger a manual run any
time from the **Actions → watch → Run workflow** button (`workflow_dispatch`).

If Craigslist starts consistently 403-blocking GitHub's runners, the fallback
is to run the same script on a Mac via `launchd` — no code changes needed,
just set the env vars.
