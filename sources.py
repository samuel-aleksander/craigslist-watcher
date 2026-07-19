"""Pluggable source definitions.

Each Source knows how to fetch and parse one site into a list of Listings.
All sources feed the shared diff-and-notify core in watcher.py, so adding
another site later is just adding another Source to `default_sources()`.
"""

import os
from dataclasses import dataclass
from typing import Callable, List

import requests
from bs4 import BeautifulSoup

# Verified working 2026-07-18. Server-rendered static HTML, no JS needed.
DEFAULT_CL_URL = (
    "https://www.craigslist.org/search/area/seattle"
    "?cat=sss&max_price=10000&min_price=2000&purveyor=owner"
    "&query=cr-v&sort=date&lang=es&cc=mx"
)

# A normal desktop browser UA gets HTTP 200 with static results.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

FETCH_TIMEOUT = 30


class SourceBlocked(Exception):
    """Raised when a source looks blocked (non-200, or zero items parsed).

    The core treats this as "do not touch state" — a captcha/block page must
    never be allowed to wipe the seen-list.
    """


@dataclass
class Listing:
    key: str
    title: str
    price: str
    url: str


def _dedupe_key(url: str) -> str:
    """The opaque token at the end of the listing URL path.

    e.g. .../tenino-2007-honda-cr-lx-.../3ihywN1uggRY1tK9wFi5Lc
    Craigslist no longer uses numeric posting IDs in these URLs.
    """
    return url.rstrip("/").split("/")[-1]


def parse_craigslist(html: str) -> List[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    listings: List[Listing] = []
    for li in soup.select("li.cl-static-search-result"):
        a = li.find("a", href=True)
        if not a:
            continue
        url = a["href"].strip()
        if not url:
            continue

        # The title lives on the <li title="..."> attribute; fall back to a
        # nested .title div or the link text.
        title = li.get("title")
        if not title:
            title_div = li.find(class_="title")
            title = title_div.get_text(strip=True) if title_div else a.get_text(strip=True)

        price_div = li.find(class_="price")
        price = price_div.get_text(strip=True) if price_div else ""

        key = _dedupe_key(url)
        if key:
            listings.append(Listing(key=key, title=title.strip(), price=price, url=url))
    return listings


@dataclass
class Source:
    name: str
    url: str
    parse: Callable[[str], List[Listing]]

    def fetch(self) -> List[Listing]:
        """Fetch and parse this source. Raises SourceBlocked on trouble."""
        resp = requests.get(
            self.url,
            headers={"User-Agent": USER_AGENT},
            timeout=FETCH_TIMEOUT,
        )
        if resp.status_code != 200:
            raise SourceBlocked(f"{self.name}: HTTP {resp.status_code}")

        listings = self.parse(resp.text)
        if not listings:
            raise SourceBlocked(f"{self.name}: zero items parsed (block/captcha?)")
        return listings


def default_sources() -> List[Source]:
    """The active source list. Add entries here to watch more sites."""
    return [
        Source(
            name="craigslist",
            url=os.environ.get("CL_URL", DEFAULT_CL_URL),
            parse=parse_craigslist,
        ),
    ]
