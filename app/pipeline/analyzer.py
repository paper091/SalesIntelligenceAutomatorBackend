"""Stage 4: turn extracted text into a validated SalesBrief via the LLM."""
from __future__ import annotations

from pydantic import ValidationError

from app.core.config import settings
from app.llm.client import LLMClient
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from app.models.schemas import ExtractedContent, SalesBrief


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
            return SalesBrief.model_validate(raw)
        except ValidationError as exc:
            last_error = exc
            continue

    raise ValueError(f"LLM output failed schema validation twice: {last_error}")
