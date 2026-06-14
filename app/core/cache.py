"""On-disk cache mapping sha256(resolved_url + extracted_text) -> SalesBrief.

Keeps re-runs of the same lead free of LLM calls during development/demos.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading

from app.core.config import settings
from app.models.schemas import SalesBrief

_lock = threading.Lock()


def cache_key(resolved_url: str, extracted_text: str) -> str:
    payload = f"{resolved_url}|{extracted_text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load() -> dict[str, dict]:
    if not os.path.exists(settings.cache_path):
        return {}
    with open(settings.cache_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def get(key: str) -> SalesBrief | None:
    with _lock:
        data = _load()
    entry = data.get(key)
    return SalesBrief.model_validate(entry) if entry is not None else None


def set(key: str, brief: SalesBrief) -> None:
    # Read-modify-write the whole file under a lock. Fine for the cache
    # sizes this project deals with; would need a real store if the
    # cache grew large or ran across multiple processes.
    with _lock:
        data = _load()
        data[key] = brief.model_dump()
        os.makedirs(os.path.dirname(settings.cache_path) or ".", exist_ok=True)
        with open(settings.cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
