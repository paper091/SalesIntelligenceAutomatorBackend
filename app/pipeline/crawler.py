"""Stage 3a: fetch homepage + a small allow-list of high-signal pages.

Tries a cheap static `httpx` fetch first; falls back to Playwright (headless
Chromium, with images/fonts/media/analytics blocked) only when the static
fetch fails or yields too little text.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

from app.core.config import settings
from app.models.schemas import PageContent

_ALLOWLIST_PATTERNS = ("about", "services", "products", "what-we-do", "contact")
_MIN_STATIC_CHARS = 200
_BLOCKED_RESOURCE_TYPES = {"image", "font", "media"}
_ANALYTICS_HOST_RE = re.compile(
    r"(google-analytics|googletagmanager|facebook\.net|hotjar|segment\.io|doubleclick)",
    re.IGNORECASE,
)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SalesIntelBot/1.0)"}


class CrawlError(Exception):
    """Raised when zero pages could be fetched for a lead."""


async def _fetch_static(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url, headers=_HEADERS, timeout=settings.request_timeout)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    return resp.text[: settings.per_page_char_cap]


def _find_allowlisted_links(base_url: str, html: str) -> list[str]:
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE)
    base_host = urlparse(base_url).hostname

    found: list[str] = []
    seen: set[str] = set()
    for href in hrefs:
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.hostname != base_host:
            continue
        path = parsed.path.lower()
        if not any(keyword in path for keyword in _ALLOWLIST_PATTERNS):
            continue
        normalized = f"{parsed.scheme}://{parsed.hostname}{parsed.path}"
        if normalized in seen:
            continue
        seen.add(normalized)
        found.append(normalized)

    return found


def _fetch_with_playwright_sync(urls: list[str]) -> dict[str, str]:
    from playwright.sync_api import sync_playwright

    results: dict[str, str] = {}

    with sync_playwright() as p:
        # Keep Chromium's memory footprint down - important on small
        # (e.g. 512MB) hosts where a couple of concurrent browser instances
        # can otherwise exhaust available memory.
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-extensions",
                "--js-flags=--max-old-space-size=128",
            ],
        )
        try:
            context = browser.new_context(user_agent=_HEADERS["User-Agent"])

            def _route_filter(route):
                request = route.request
                if request.resource_type in _BLOCKED_RESOURCE_TYPES or _ANALYTICS_HOST_RE.search(request.url):
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", _route_filter)

            for url in urls:
                page = context.new_page()
                try:
                    page.goto(url, timeout=settings.request_timeout * 1000, wait_until="domcontentloaded")
                    # Many sites render their actual copy client-side after
                    # the initial DOM load, so give the page a bit longer to
                    # settle before grabbing its HTML. If it never goes idle
                    # (e.g. polling/analytics), fall back to whatever loaded.
                    try:
                        page.wait_for_load_state("networkidle", timeout=settings.request_timeout * 1000)
                    except Exception:
                        pass
                    html = page.content()
                    results[url] = html[: settings.per_page_char_cap]
                except Exception:
                    continue
                finally:
                    page.close()
        finally:
            browser.close()

    return results


async def _fetch_with_playwright(urls: list[str]) -> dict[str, str]:
    """Run Playwright's sync API in a worker thread.

    The async Playwright API requires the Proactor event loop for subprocess
    support on Windows, which uvicorn's event loop may not be using. The sync
    API run on a separate thread avoids that dependency entirely.
    """
    if not settings.enable_js_rendering:
        return {}
    return await asyncio.to_thread(_fetch_with_playwright_sync, urls)


async def crawl(url: str) -> list[PageContent]:
    """Fetch the homepage plus up to `MAX_PAGES - 1` allow-listed internal pages.

    Raises CrawlError if zero pages could be fetched.
    """
    pages: list[PageContent] = []
    needs_playwright_urls: list[str] = []

    async with httpx.AsyncClient(follow_redirects=True) as client:
        homepage_html = await _fetch_static(client, url)

        # If the static fetch returned enough real content, trust it and look
        # for more pages from this same HTML. Otherwise assume the site is
        # JS-rendered and queue it for the Playwright fallback below.
        if homepage_html and len(trafilatura.extract(homepage_html, include_comments=False) or "") >= _MIN_STATIC_CHARS:
            pages.append(PageContent(url=url, html=homepage_html))
            link_targets = _find_allowlisted_links(url, homepage_html)[: settings.max_pages - 1]
            for link in link_targets:
                html = await _fetch_static(client, link)
                if html and len(trafilatura.extract(html, include_comments=False) or "") >= _MIN_STATIC_CHARS:
                    pages.append(PageContent(url=link, html=html))
                else:
                    needs_playwright_urls.append(link)
        else:
            needs_playwright_urls.append(url)
            if homepage_html:
                link_targets = _find_allowlisted_links(url, homepage_html)[: settings.max_pages - 1]
                needs_playwright_urls.extend(link_targets)

    needs_playwright_urls = needs_playwright_urls[: settings.max_pages - len(pages)]

    if needs_playwright_urls:
        try:
            rendered = await _fetch_with_playwright(needs_playwright_urls)
        except Exception:
            rendered = {}

        for fetched_url, html in rendered.items():
            pages.append(PageContent(url=fetched_url, html=html))

    if not pages:
        raise CrawlError(f"Failed to fetch any pages for {url}")

    return pages[: settings.max_pages]
