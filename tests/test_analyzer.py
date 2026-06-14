import json

import pytest

from app.llm.client import LLMClient
from app.models.schemas import ExtractedContent
from app.pipeline.analyzer import analyze

VALID_BRIEF = {
    "company_overview": "Acme Roofing installs and repairs roofs for homes and businesses in Dallas.",
    "core_product_or_service": "Residential and commercial roofing installation and repair.",
    "target_customer": "Homeowners and commercial property owners in the Dallas area.",
    "b2b_qualified": False,
    "b2b_reasoning": "Primarily serves individual homeowners, a B2C consumer service.",
    "sales_questions": [
        "What is your current roof replacement cycle?",
        "Do you handle commercial roofing contracts?",
        "What materials do you typically install?",
    ],
    "confidence": "high",
    "evidence_note": None,
}

INVALID_THEN_VALID = [
    {"company_overview": "missing fields"},
    VALID_BRIEF,
]


class StubLLMClient(LLMClient):
    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls = 0

    async def complete_json(self, system: str, user: str, model: str) -> dict:
        self.calls += 1
        return self._responses[self.calls - 1]


@pytest.mark.asyncio
async def test_analyze_returns_valid_brief():
    llm = StubLLMClient([VALID_BRIEF])
    extracted = ExtractedContent(text="Some real content about Acme Roofing.", source_pages=["https://acme.com/"])

    brief = await analyze(llm, "Acme Roofing", extracted)

    assert brief.model_dump() == VALID_BRIEF
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_analyze_retries_once_on_invalid_json_shape():
    llm = StubLLMClient(INVALID_THEN_VALID)
    extracted = ExtractedContent(text="Some real content about Acme Roofing.", source_pages=["https://acme.com/"])

    brief = await analyze(llm, "Acme Roofing", extracted)

    assert brief.b2b_qualified is False
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_analyze_skips_llm_for_empty_thin_content():
    llm = StubLLMClient([VALID_BRIEF])
    extracted = ExtractedContent(text="", source_pages=[], thin_content=True)

    brief = await analyze(llm, "Unknown Co", extracted)

    assert brief.confidence == "low"
    assert brief.b2b_qualified is False
    assert llm.calls == 0
