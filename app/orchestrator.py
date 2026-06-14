"""Runs the intake -> resolve -> crawl -> extract -> analyze pipeline for a
batch of leads, concurrently and with each lead isolated from the others.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from app.core import cache
from app.core.config import settings
from app.llm.client import LLMClient
from app.models.db import LeadRepository
from app.models.schemas import ExtractedContent, LeadInput, LeadResult, SalesBrief
from app.pipeline import resolver
from app.pipeline.analyzer import analyze
from app.pipeline.crawler import CrawlError, crawl
from app.pipeline.extractor import extract_content


def new_lead_result(lead_input: LeadInput) -> LeadResult:
    now = datetime.now(timezone.utc)
    return LeadResult(
        id=str(uuid.uuid4()),
        input=lead_input,
        status="pending",
        created_at=now,
        updated_at=now,
    )


async def _brief_from_search(llm: LLMClient, lead: LeadResult) -> SalesBrief | None:
    """Last-resort path: when there's no website to crawl (or it won't load),
    fall back to plain search-result snippets so we can still produce a
    (lower-confidence) brief instead of just giving up on the lead.
    """
    results = await resolver.search_snippets(lead.input.name or lead.input.raw, lead.input.location_hint)
    chunks = [f"{r['title']}\n{r['snippet']}\n{r['url']}" for r in results if r["snippet"]]
    if not chunks:
        return None

    text = "\n\n".join(chunks)
    extracted = ExtractedContent(text=text, source_pages=[r["url"] for r in results], thin_content=True)
    company_hint = lead.input.name or lead.input.raw
    return await analyze(llm, company_hint, extracted)


def _note_search_fallback(brief: SalesBrief, reason: str) -> SalesBrief:
    note = f"{reason} This brief is based on search-result snippets, not the company's website."
    brief.evidence_note = f"{brief.evidence_note} {note}" if brief.evidence_note else note
    return brief


async def process_lead(repo: LeadRepository, llm: LLMClient, lead: LeadResult) -> None:
    """Run one lead through the full pipeline, updating its status in the
    repository at each transition. Any error marks the lead `failed` without
    raising, so one bad lead never breaks the batch.
    """
    try:
        lead.status = "processing"
        repo.update(lead)

        # Stage 2: resolve name -> URL if needed.
        url = lead.input.url
        if not url:
            url = await resolver.resolve(lead.input.name or "", lead.input.location_hint)
            if not url:
                # No website found - try to still say something useful from
                # search results before giving up entirely.
                brief = await _brief_from_search(llm, lead)
                if brief is None:
                    lead.status = "failed"
                    lead.error = "Could not resolve a website URL for this lead."
                    repo.update(lead)
                    return
                lead.brief = _note_search_fallback(brief, "No official website could be found.")
                lead.status = "done"
                repo.update(lead)
                return
        lead.resolved_url = url
        repo.update(lead)

        # Stage 3: crawl + extract.
        try:
            pages = await crawl(url)
        except CrawlError as exc:
            # The site wouldn't load - same fallback as the no-URL case above.
            brief = await _brief_from_search(llm, lead)
            if brief is None:
                lead.status = "failed"
                lead.error = str(exc)
                repo.update(lead)
                return
            lead.brief = _note_search_fallback(brief, f"The website could not be loaded ({exc}).")
            lead.status = "done"
            repo.update(lead)
            return

        extracted = extract_content(pages)

        # Stage 4: analyze (with cache).
        key = cache.cache_key(url, extracted.text)
        brief = cache.get(key)
        if brief is None:
            company_hint = lead.input.name or lead.input.raw
            brief = await analyze(llm, company_hint, extracted)
            cache.set(key, brief)

        lead.brief = brief
        lead.status = "done"
        repo.update(lead)

    except Exception as exc:  # noqa: BLE001 - isolate failures per lead
        lead.status = "failed"
        lead.error = f"{type(exc).__name__}: {exc}"
        repo.update(lead)


async def process_batch(repo: LeadRepository, llm: LLMClient, leads: list[LeadResult]) -> None:
    # Cap how many leads crawl/analyze at once so a big batch doesn't open
    # dozens of browser tabs or blow through the LLM rate limit at once.
    semaphore = asyncio.Semaphore(settings.max_concurrent_leads)

    async def _bounded(lead: LeadResult) -> None:
        async with semaphore:
            await process_lead(repo, llm, lead)

    await asyncio.gather(*(_bounded(lead) for lead in leads))
