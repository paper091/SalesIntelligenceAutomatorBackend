"""Stage 4: turn extracted text into a validated SalesBrief via the LLM."""
from __future__ import annotations

from typing import Literal

from pydantic import ValidationError

from app.core.config import settings
from app.llm.client import LLMClient
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from app.models.schemas import ExtractedContent, SalesBrief

# Thresholds for the deterministic confidence score (see _assess_confidence).
_RICH_TEXT_CHARS = 2000
_OK_TEXT_CHARS = 800


def _thin_content_brief(reason: str) -> SalesBrief:
    return SalesBrief(
        company_overview="Unknown",
        core_product_or_service="Unknown",
        target_customer="Unknown",
        b2b_qualified=False,
        b2b_reasoning="Insufficient evidence from the website to determine B2B fit.",
        sales_questions=[
            "What does your company do and who are your typical customers?",
            "What products or services do you offer?",
            "What challenges are you currently trying to solve?",
        ],
        confidence="low",
        evidence_note=reason,
    )


def _assess_confidence(
    brief: SalesBrief, extracted: ExtractedContent
) -> tuple[Literal["low", "medium", "high"], str]:
    """Score how much we trust this brief from observable data quality, rather
    than asking the model to grade its own work.

    The drivers: how much text we had, how many pages corroborated it, whether
    key fields came back Unknown, and whether the B2B call rests on real
    evidence. Search-snippet sources (thin_content) are capped at medium since
    they're second-hand. Returns the level plus a short human rationale.
    """
    score = 0

    text_len = len(extracted.text)
    if text_len >= _RICH_TEXT_CHARS:
        score += 2
    elif text_len >= _OK_TEXT_CHARS:
        score += 1

    page_count = len(extracted.source_pages)
    if page_count >= 3:
        score += 1

    if brief.b2b_signals:
        score += 1

    unknowns = sum(
        1
        for value in (brief.company_overview, brief.core_product_or_service, brief.target_customer)
        if value.strip().lower().startswith("unknown")
    )
    score -= unknowns

    if extracted.thin_content:
        # Second-hand / sparse source: never better than medium.
        level: Literal["low", "medium", "high"] = "medium" if score >= 2 else "low"
    elif score >= 4:
        level = "high"
    elif score >= 2:
        level = "medium"
    else:
        level = "low"

    signal_note = "B2B signals found" if brief.b2b_signals else "no clear B2B signals"
    detail = "from search snippets" if extracted.thin_content else f"from {page_count} page(s)"
    rationale = f"Confidence {level}: {detail}, {signal_note}."
    if unknowns:
        rationale += f" {unknowns} key field(s) unknown."

    return level, rationale


async def analyze(llm: LLMClient, company_hint: str, extracted: ExtractedContent) -> SalesBrief:
    """Produce a SalesBrief for one lead. Validates the LLM's JSON output
    against the SalesBrief schema, retrying once on failure.
    """
    # If the crawler/extractor couldn't pull any real text, skip the LLM call
    # entirely - there's nothing for it to work with, and it would just guess.
    if extracted.thin_content and not extracted.text.strip():
        return _thin_content_brief("No usable content was extracted from the website.")

    user_prompt = build_user_prompt(company_hint, extracted.source_pages, extracted.text)

    last_error: Exception | None = None
    for attempt in range(2):
        prompt = user_prompt
        if attempt == 1 and last_error is not None:
            # Second try: tell the model exactly what was wrong with its
            # first attempt instead of just re-asking the same question.
            prompt += f"\n\nYour previous response was invalid: {last_error}. Return corrected JSON only."

        raw = await llm.complete_json(SYSTEM_PROMPT, prompt, model=settings.analysis_model)
        try:
            brief = SalesBrief.model_validate(raw)
        except ValidationError as exc:
            last_error = exc
            continue

        # Confidence is ours to compute, not the model's to guess.
        level, rationale = _assess_confidence(brief, extracted)
        brief.confidence = level
        brief.evidence_note = (
            f"{brief.evidence_note} {rationale}".strip() if brief.evidence_note else rationale
        )
        return brief

    raise ValueError(f"LLM output failed schema validation twice: {last_error}")
