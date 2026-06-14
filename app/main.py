"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import settings
from app.models.db import LeadRepository, SqliteLeadRepository

app = FastAPI(title="Sales Intelligence Automator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# A single shared repository instance for the life of the process. Routes
# and background tasks both fetch it through get_repository() so they're
# always reading/writing the same SQLite connection.
_repository: LeadRepository = SqliteLeadRepository(settings.db_path)


def get_repository() -> LeadRepository:
    return _repository


app.include_router(router)
