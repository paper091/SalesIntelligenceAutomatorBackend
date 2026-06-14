"""Stage 1: normalize raw lead text into structured LeadInput objects."""
from __future__ import annotations

import re

from app.models.schemas import LeadInput

_URL_RE = re.compile(r"^(https?://)?[\w.-]+\.[a-z]{2,}(/.*)?$", re.IGNORECASE)
_LOCATION_RE = re.compile(r",\s*([A-Za-z .]+?)\s*([A-Z]{2})?$")


def _looks_like_url(token: str) -> bool:
    return bool(_URL_RE.match(token.strip()))


def _normalize_url(token: str) -> str:
    token = token.strip()
    if not re.match(r"^https?://", token, re.IGNORECASE):
        token = f"https://{token}"
    # Lowercase the scheme + host, leave the path alone.
    match = re.match(r"^(https?://)([^/]+)(/.*)?$", token, re.IGNORECASE)
    if not match:
        return token
    scheme, host, path = match.group(1).lower(), match.group(2).lower(), match.group(3) or ""
    return f"{scheme}{host}{path}"


def _split_name_and_location(name: str) -> tuple[str, str | None]:
    """Split "Acme Roofing - Dallas TX" into ("Acme Roofing", "Dallas TX")."""
    # Trailing " - City ST" or ", City ST" style suffix.
    for sep in (" - ", " – ", ","):
        if sep in name:
            head, _, tail = name.rpartition(sep)
            tail = tail.strip()
            if head and tail and len(tail.split()) <= 4:
                return head.strip(), tail
    return name.strip(), None


def parse_leads(raw_text: str) -> list[LeadInput]:
    """Parse a newline-delimited blob of leads into deduped LeadInput objects."""
    leads: list[LeadInput] = []
    seen: set[str] = set()

    for line in raw_text.splitlines():
        line = line.strip().strip(",")
        if not line:
            continue

        if _looks_like_url(line):
            url = _normalize_url(line)
            key = url
            if key in seen:
                continue
            seen.add(key)
            leads.append(LeadInput(raw=line, url=url))
        else:
            name, location_hint = _split_name_and_location(line)
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            leads.append(LeadInput(raw=line, name=name, location_hint=location_hint))

    return leads
