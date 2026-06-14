"""API endpoints for submitting leads and polling results."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.llm.client import LLMClient, get_llm_client
from app.models.db import LeadRepository
from app.models.schemas import LeadResult
from app.orchestrator import new_lead_result, process_batch
from app.pipeline.export import build_workbook
from app.pipeline.intake import parse_leads

router = APIRouter()


def get_repo() -> LeadRepository:
    # Imported here, not at module load time, to avoid a circular import
    # with app.main (which imports this router).
    from app.main import get_repository

    return get_repository()


def get_llm() -> LLMClient:
    return get_llm_client()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/leads", response_model=list[LeadResult])
async def submit_leads(
    background_tasks: BackgroundTasks,
    leads: str | None = Form(default=None),
    file: UploadFile | None = None,
    repo: LeadRepository = Depends(get_repo),
    llm: LLMClient = Depends(get_llm),
) -> list[LeadResult]:
    if file is not None:
        raw_bytes = await file.read()
        raw_text = raw_bytes.decode("utf-8", errors="ignore")
    elif leads is not None:
        raw_text = leads
    else:
        raise HTTPException(status_code=400, detail="Provide either 'leads' text or a file upload.")

    lead_inputs = parse_leads(raw_text)
    if not lead_inputs:
        raise HTTPException(status_code=400, detail="No valid leads found in input.")

    results = [new_lead_result(li) for li in lead_inputs]
    for result in results:
        repo.save(result)

    # Hand the actual research off to a background task so the client gets
    # an immediate response with "pending" rows and polls for updates.
    background_tasks.add_task(process_batch, repo, llm, results)
    return results


@router.get("/api/leads", response_model=list[LeadResult])
async def list_leads(repo: LeadRepository = Depends(get_repo)) -> list[LeadResult]:
    return repo.list()


@router.delete("/api/leads", status_code=204)
async def clear_leads(repo: LeadRepository = Depends(get_repo)) -> Response:
    repo.clear()
    return Response(status_code=204)


@router.get("/api/leads/export")
async def export_leads(repo: LeadRepository = Depends(get_repo)) -> Response:
    # Declared before /api/leads/{lead_id} so FastAPI doesn't match
    # "export" as a lead_id path parameter.
    leads = repo.list()
    content = build_workbook(leads)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=sales_briefs.xlsx"},
    )


@router.get("/api/leads/{lead_id}", response_model=LeadResult)
async def get_lead(lead_id: str, repo: LeadRepository = Depends(get_repo)) -> LeadResult:
    lead = repo.get(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead
