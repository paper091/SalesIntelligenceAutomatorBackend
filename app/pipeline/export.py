"""Build an .xlsx workbook summarizing lead results for download."""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Font

from app.models.schemas import LeadResult

_HEADERS = [
    "Lead",
    "Resolved URL",
    "Status",
    "B2B Qualified",
    "B2B Reasoning",
    "Confidence",
    "Company Overview",
    "Core Product / Service",
    "Target Customer",
    "Sales Question 1",
    "Sales Question 2",
    "Sales Question 3",
    "Evidence Note",
    "Error",
]


def build_workbook(leads: list[LeadResult]) -> bytes:
    """Render lead results into an in-memory .xlsx workbook and return its bytes."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sales Briefs"

    ws.append(_HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for lead in leads:
        brief = lead.brief
        questions = (brief.sales_questions if brief else []) + ["", "", ""]
        ws.append([
            lead.input.name or lead.input.url or lead.input.raw,
            lead.resolved_url or "N/A",
            lead.status,
            "Yes" if brief and brief.b2b_qualified else ("No" if brief else ""),
            brief.b2b_reasoning if brief else "",
            brief.confidence if brief else "",
            brief.company_overview if brief else "",
            brief.core_product_or_service if brief else "",
            brief.target_customer if brief else "",
            questions[0],
            questions[1],
            questions[2],
            brief.evidence_note if brief and brief.evidence_note else "",
            lead.error or "",
        ])

    # Auto-size columns to their content, capped so a long brief doesn't
    # produce an unreadably wide column.
    for column_cells in ws.columns:
        max_length = max(len(str(c.value)) if c.value is not None else 0 for c in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = min(max_length + 2, 60)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
