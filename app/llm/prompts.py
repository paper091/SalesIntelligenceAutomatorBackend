"""System prompt and JSON schema for the sales-brief analyzer.

Keeping the rubric here, in one place, makes the B2B decision consistent
across leads and lets the ICP be swapped with a one-line edit.
"""
from __future__ import annotations

from app.models.schemas import SalesBrief

# Default ICP rubric (Locked Decision #3 in the README). Edit this block to
# change the qualification bar for all leads.
B2B_RUBRIC = (
    "Qualified (true) only if the company PRIMARILY sells products or services to "
    "OTHER BUSINESSES. Local consumer home-services businesses that sell directly "
    "to homeowners or the general public — e.g. residential roofing, lawn care, "
    "plumbing, auto repair, bakeries, moving for individuals — are B2C and should "
    "be marked false, UNLESS the text clearly shows a commercial, contractor, "
    "property-management, or wholesale offering is a core part of the business."
)

# Signals the model should weigh. Listing them explicitly keeps the decision
# consistent and forces the model to point at concrete evidence.
_B2B_SIGNALS = (
    '- Language aimed at businesses: "for your business", "for facilities", '
    '"commercial clients", "contractors", "wholesale", "bulk", "trade pricing", '
    '"partner with us", "request a corporate quote", "for property managers".\n'
    "- Customers named are companies, institutions, governments, or resellers.\n"
    "- Products/services that only other businesses buy (e.g. fulfillment, "
    "white-label manufacturing, B2B SaaS, distribution)."
)

_B2C_SIGNALS = (
    '- Language aimed at individuals: "for your home", "homeowners", "families", '
    '"book an appointment", "residential", "DIY", consumer pricing/menus.\n'
    "- Storefront, restaurant, or personal-service framing with no business-buyer track."
)

SALES_BRIEF_JSON_SCHEMA: dict = SalesBrief.model_json_schema()


def _llm_response_schema() -> dict:
    """Schema we actually ask the LLM to fill.

    Confidence is computed by the pipeline from data-quality signals (not by
    the model), so we strip it out of the schema the model sees.
    """
    schema = SalesBrief.model_json_schema()
    schema.get("properties", {}).pop("confidence", None)
    if "required" in schema:
        schema["required"] = [r for r in schema["required"] if r != "confidence"]
    return schema


SYSTEM_PROMPT = f"""You are a sales research assistant. You will be given cleaned text \
extracted from a company's website (or, occasionally, from search-result snippets). \
Produce a structured sales brief using ONLY the information present in that text.

Rules:
- Never use outside knowledge or invent facts. Base every field strictly on the provided text.
- If the text does not contain enough information for a field, set that field to "Unknown" \
(or, for sales_questions, write a generic discovery question about their business).

How to decide b2b_qualified:
1. Work out WHO this company sells to, based only on the text.
2. Weigh these B2B signals:
{_B2B_SIGNALS}
3. Against these B2C signals:
{_B2C_SIGNALS}
4. Apply the rubric: {B2B_RUBRIC}
5. If the evidence is mixed or thin, default to false and say so.

Put the concrete phrases or facts that drove your decision in b2b_signals (short \
quotes or paraphrases from the text — not your reasoning). Explain the verdict in \
b2b_reasoning, referring to those signals. If you genuinely found no relevant signals, \
return an empty b2b_signals list.

sales_questions must be THREE specific discovery questions a sales rep could ask THIS \
company, based on what the text says they do — not generic boilerplate.

Respond with a single JSON object matching this schema:
{_llm_response_schema()}
"""


def build_user_prompt(company_hint: str, source_pages: list[str], text: str) -> str:
    pages_str = ", ".join(source_pages) or "unknown"
    return (
        f"Company / lead reference: {company_hint}\n"
        f"Source pages: {pages_str}\n\n"
        f"Extracted website text:\n---\n{text}\n---"
    )
