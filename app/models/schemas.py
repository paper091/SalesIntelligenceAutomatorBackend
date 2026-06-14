"""Pydantic data models shared across the pipeline and API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LeadInput(BaseModel):
    """A single normalized lead, as produced by the intake stage."""

    raw: str
    name: str | None = None
    url: str | None = None
    location_hint: str | None = None


class SalesBrief(BaseModel):
    """The structured output produced by the LLM analyzer.

    This model doubles as the JSON schema sent to the LLM in JSON mode, so the
    five assignment-required fields (overview, product, target, B2B decision,
    three questions) are always present and well-typed.
    """

    company_overview: str
    core_product_or_service: str
    target_customer: str
    b2b_qualified: bool
    b2b_reasoning: str
    # Concrete phrases/evidence from the page that drove the B2B decision, so
    # the call is auditable instead of a black-box yes/no.
    b2b_signals: list[str] = Field(default_factory=list)
    sales_questions: list[str] = Field(min_length=3, max_length=3)
    # Computed by the analyzer from data-quality signals, not asked of the LLM,
    # so it defaults here and is overwritten after analysis.
    confidence: Literal["low", "medium", "high"] = "low"
    evidence_note: str | None = None


class PageContent(BaseModel):
    """Raw HTML for a single crawled page."""

    url: str
    html: str


class ExtractedContent(BaseModel):
    """Cleaned, de-duplicated, truncated text ready for the LLM."""

    text: str
    source_pages: list[str]
    thin_content: bool = False


class LeadResult(BaseModel):
    """Persisted record for a lead, tracked through the pipeline."""

    id: str
    input: LeadInput
    status: Literal["pending", "processing", "done", "failed"] = "pending"
    resolved_url: str | None = None
    brief: SalesBrief | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
