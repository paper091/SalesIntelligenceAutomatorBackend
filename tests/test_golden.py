"""End-to-end golden test: intake -> extract -> analyze (mocked LLM) -> schema check."""
import pytest

from app.llm.client import LLMClient
from app.models.schemas import SalesBrief, PageContent
from app.pipeline.analyzer import analyze
from app.pipeline.extractor import extract_content
from app.pipeline.intake import parse_leads

SAMPLE_LEADS_TEXT = """https://www.example-roofing.com
Acme Roofing & Construction - Dallas TX"""

ROOFING_HTML = """
<html><body>
<main>
<h1>Example Roofing</h1>
<p>Example Roofing provides residential roof repair, replacement, and inspection
services to homeowners throughout the metro area. We also partner with property
management companies for multi-unit roofing maintenance contracts.</p>
</main>
</body></html>
"""

MOCK_BRIEF = {
    "company_overview": "Example Roofing repairs and replaces roofs for homeowners and property managers.",
    "core_product_or_service": "Residential roof repair, replacement, and inspection.",
    "target_customer": "Homeowners and property management companies.",
    "b2b_qualified": True,
    "b2b_reasoning": "Maintains commercial contracts with property management companies, a B2B offering.",
    "sales_questions": [
        "How many properties does your portfolio currently include?",
        "Do you have an existing roofing maintenance contract?",
        "What is your typical timeline for inspections?",
    ],
    "confidence": "medium",
    "evidence_note": None,
}


class StubLLMClient(LLMClient):
    async def complete_json(self, system: str, user: str, model: str) -> dict:
        return MOCK_BRIEF


@pytest.mark.asyncio
async def test_golden_pipeline_produces_valid_brief():
    leads = parse_leads(SAMPLE_LEADS_TEXT)
    assert len(leads) == 2

    url_lead = leads[0]
    assert url_lead.url == "https://www.example-roofing.com"

    extracted = extract_content([PageContent(url=url_lead.url, html=ROOFING_HTML)])
    assert not extracted.thin_content

    brief = await analyze(StubLLMClient(), "Example Roofing", extracted)

    assert isinstance(brief, SalesBrief)
    assert brief.company_overview
    assert brief.core_product_or_service
    assert brief.target_customer
    assert isinstance(brief.b2b_qualified, bool)
    assert len(brief.sales_questions) == 3
