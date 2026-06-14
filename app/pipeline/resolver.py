"""Stage 2: resolve a company name (+ optional location) to a homepage URL.

Behind a single `resolve()` interface so a richer search provider (e.g. Exa)
can be swapped in later without touching the orchestrator.
"""
from __future__ import annotations

import re

import httpx

_SEARCH_URL = "https://duckduckgo.com/html/"

_DIRECTORY_HOSTS = {
    "facebook.com", "yelp.com", "linkedin.com", "instagram.com", "twitter.com",
    "x.com", "yellowpages.com", "bbb.org", "mapquest.com", "indeed.com",
    "tiktok.com", "youtube.com", "angi.com", "thumbtack.com", "google.com",
    "maps.google.com", "wikipedia.org",
}

_RESULT_LINK_RE = re.compile(r'href="(https?://[^"]+)"')


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
                headers={"User-Agent": "Mozilla/5.0 (compatible; SalesIntelBot/1.0)"},
            )
            resp.raise_for_status()
    except httpx.HTTPError:
        return None

    for raw_url in _RESULT_LINK_RE.findall(resp.text):
        candidate = _unwrap_redirect(raw_url)
        host = _hostname(candidate)
        if not host or _is_directory(host):
            continue
        return candidate

    return None


def _unwrap_redirect(url: str) -> str:
    """DuckDuckGo wraps results in /l/?uddg=<encoded url>; unwrap if present."""
    if "uddg=" in url:
        from urllib.parse import parse_qs, unquote, urlparse

        qs = parse_qs(urlparse(url).query)
        target = qs.get("uddg")
        if target:
            return unquote(target[0])
    return url


def _hostname(url: str) -> str | None:
    from urllib.parse import urlparse

    try:
        return urlparse(url).hostname
    except ValueError:
        return None


def _is_directory(host: str) -> bool:
    host = host.lower().lstrip("www.")
    return any(host == d or host.endswith(f".{d}") for d in _DIRECTORY_HOSTS)
