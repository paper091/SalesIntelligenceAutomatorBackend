"""Stage 3b: turn raw HTML into clean, de-duplicated, budget-capped text."""
from __future__ import annotations

import hashlib

import trafilatura
from readability import Document

from app.core.config import settings
from app.models.schemas import ExtractedContent, PageContent

# Pages matching these path fragments are kept first when truncating, since
# they tend to carry the highest-signal "what we do" content.
_PRIORITY_ORDER = ("about", "services", "products", "what-we-do", "/")

_MIN_CONTENT_CHARS = 400


def _extract_page_text(html: str) -> str:
    text = trafilatura.extract(html, include_comments=False, include_tables=False)
    if text and text.strip():
        return text.strip()

    # Fallback for pages trafilatura can't parse.
    try:
        doc = Document(html)
        summary_html = doc.summary()
        fallback = trafilatura.extract(summary_html, include_comments=False)
        return (fallback or "").strip()
    except Exception:
        return ""


def _block_hash(block: str) -> str:
    normalized = " ".join(block.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _priority_rank(url: str) -> int:
    path = url.lower()
    for i, keyword in enumerate(_PRIORITY_ORDER):
        if keyword in path:
            return i
    return len(_PRIORITY_ORDER)


def extract_content(pages: list[PageContent]) -> ExtractedContent:
    """Extract clean text from each page, drop blocks repeated across pages,
    order by priority, and truncate to the configured character budget.
    """
    page_blocks: dict[str, list[str]] = {}
    block_counts: dict[str, int] = {}

    for page in pages:
        text = _extract_page_text(page.html)
        blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
        page_blocks[page.url] = blocks
        for block in blocks:
            h = _block_hash(block)
            block_counts[h] = block_counts.get(h, 0) + 1

    ordered_pages = sorted(pages, key=lambda p: _priority_rank(p.url))

    kept_chunks: list[str] = []
    contributing: list[str] = []
    total_chars = 0

    for page in ordered_pages:
        page_kept: list[str] = []
        for block in page_blocks.get(page.url, []):
            if block_counts.get(_block_hash(block), 0) > 1:
                continue  # repeated across pages -> nav/footer/boilerplate
            page_kept.append(block)

        if not page_kept:
            continue

        page_text = "\n\n".join(page_kept)
        remaining = settings.char_budget - total_chars
        if remaining <= 0:
            break
        if len(page_text) > remaining:
            page_text = page_text[:remaining]

        kept_chunks.append(page_text)
        contributing.append(page.url)
        total_chars += len(page_text)

    full_text = "\n\n".join(kept_chunks)
    return ExtractedContent(
        text=full_text,
        source_pages=contributing,
        thin_content=len(full_text) < _MIN_CONTENT_CHARS,
    )
