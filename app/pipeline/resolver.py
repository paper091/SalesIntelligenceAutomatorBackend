"""Stage 2: resolve a company name (+ optional location) to a homepage URL.

Also exposes `search_snippets()`, which the orchestrator falls back to when
no website can be found or crawled - search-result titles/snippets are enough
for the LLM to produce a (lower-confidence) brief instead of just failing.

Behind these two functions so a richer search provider (e.g. Exa) can be
swapped in later without touching the orchestrator.
"""
from __future__ import annotations

import re

import httpx

from app.core.config import settings

_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"

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

# Lite's results are simple HTML tables: a result-link <a>, optionally
# followed by a result-snippet <td> before the next result-link.
_LINK_RE = re.compile(r"<a rel=\"nofollow\" href=\"([^\"]+)\" class='result-link'>(.*?)</a>", re.DOTALL)
_SNIPPET_RE = re.compile(r"<td class='result-snippet'>(.*?)</td>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


async def resolve(name: str, location_hint: str | None = None) -> str | None:
    """Best-effort name -> homepage URL resolution via a plain search query.

    Returns None if no confident, non-directory result is found. Never raises.
    """
    query = f"{name} {location_hint or ''} official site".strip()
    results = await _search(query, max_results=10)

    for result in results:
        host = _hostname(result["url"])
        if host and not _is_directory(host):
            return result["url"]

    return None


async def search_snippets(name: str, location_hint: str | None = None, max_results: int = 5) -> list[dict]:
    """Plain web search for a company, returning [{url, title, snippet}, ...].

    Used as a last resort when there's no usable website to crawl - the
    snippets alone often carry enough signal for a rough brief.
    """
    query = f"{name} {location_hint or ''}".strip()
    return await _search(query, max_results=max_results)


async def _search(query: str, max_results: int) -> list[dict]:
    """Return [{url, title, snippet}, ...] from whichever backend is available.

    Prefers Brave's API (stable, free tier); falls back to scraping
    DuckDuckGo's lite endpoint when no Brave key is configured or the API
    call fails.
    """
    if settings.brave_api_key:
        results = await _search_brave(query, max_results)
        if results:
            return results

    return await _search_duckduckgo(query, max_results)


async def _search_brave(query: str, max_results: int) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                _BRAVE_URL,
                params={"q": query, "count": max_results},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": settings.brave_api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    results: list[dict] = []
    for item in data.get("web", {}).get("results", [])[:max_results]:
        url = item.get("url")
        if not url:
            continue
        results.append({
            "url": url,
            "title": _clean(item.get("title", "")),
            "snippet": _clean(item.get("description", "")),
        })
    return results


async def _search_duckduckgo(query: str, max_results: int) -> list[dict]:
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
        return []

    html = resp.text
    links = list(_LINK_RE.finditer(html))
    snippets = list(_SNIPPET_RE.finditer(html))

    results: list[dict] = []
    for i, link in enumerate(links):
        url = _unwrap_redirect(link.group(1))
        if url is None:
            continue

        # The snippet for this result sits between this link and the next one.
        window_end = links[i + 1].start() if i + 1 < len(links) else len(html)
        snippet = ""
        for s in snippets:
            if link.end() <= s.start() < window_end:
                snippet = _clean(s.group(1))
                break

        results.append({"url": url, "title": _clean(link.group(2)), "snippet": snippet})
        if len(results) >= max_results:
            break

    return results


def _clean(html: str) -> str:
    """Strip tags and collapse whitespace from a snippet/title fragment."""
    return re.sub(r"\s+", " ", _TAG_RE.sub("", html)).strip()


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
