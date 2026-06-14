"""Stage 2: resolve a company name (+ optional location) to a homepage URL.

Behind a single `resolve()` interface so a richer search provider (e.g. Exa)
can be swapped in later without touching the orchestrator.
"""
from __future__ import annotations

import re

import httpx

# The regular /html/ endpoint now shows a "select all squares with a duck"
# bot challenge to non-browser requests. The lite endpoint still returns
# plain result links without one.
_SEARCH_URL = "https://lite.duckduckgo.com/lite/"

_DIRECTORY_HOSTS = {
    "facebook.com", "yelp.com", "linkedin.com", "instagram.com", "twitter.com",
    "x.com", "yellowpages.com", "bbb.org", "mapquest.com", "indeed.com",
    "tiktok.com", "youtube.com", "angi.com", "thumbtack.com", "google.com",
    "maps.google.com", "wikipedia.org",
}

# Lite's result links are scheme-relative (e.g. //duckduckgo.com/l/?uddg=...),
# so match any href and let _unwrap_redirect sort out what's a real result.
_RESULT_LINK_RE = re.compile(r'href="([^"]+)"')


async def resolve(name: str, location_hint: str | None = None) -> str | None:
    """Best-effort name -> homepage URL resolution via a plain search query.

    Returns None if no confident, non-directory result is found. Never raises.
    """
    query = f"{name} {location_hint or ''} official site".strip()

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(
                _SEARCH_URL,
                params={"q": query},
                headers={
                    # A real browser UA matters here - DuckDuckGo's anti-bot
                    # checks are picky about this even on the lite endpoint.
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                    ),
                },
            )
            resp.raise_for_status()
    except httpx.HTTPError:
        return None

    for raw_url in _RESULT_LINK_RE.findall(resp.text):
        candidate = _unwrap_redirect(raw_url)
        if candidate is None:
            continue
        host = _hostname(candidate)
        if not host or _is_directory(host):
            continue
        return candidate

    return None


def _unwrap_redirect(url: str) -> str | None:
    """Pull the real target out of DuckDuckGo's /l/?uddg=<encoded url> wrapper.

    Returns None for anything that isn't one of these wrapped result links
    (nav links, asset links, etc).
    """
    if "uddg=" not in url:
        return None

    from urllib.parse import parse_qs, unquote, urlparse

    qs = parse_qs(urlparse(url).query)
    target = qs.get("uddg")
    return unquote(target[0]) if target else None


def _hostname(url: str) -> str | None:
    from urllib.parse import urlparse

    try:
        return urlparse(url).hostname
    except ValueError:
        return None


def _is_directory(host: str) -> bool:
    host = host.lower().lstrip("www.")
    return any(host == d or host.endswith(f".{d}") for d in _DIRECTORY_HOSTS)
