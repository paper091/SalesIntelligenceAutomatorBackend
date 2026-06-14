# Sales Intelligence Automator — Backend

Automated lead research for sales teams. Give it a list of company names or website URLs;
it crawls the web, extracts the meaningful content, and uses an LLM to produce a structured
sales brief for each lead.

This is the **backend** service: a Python/FastAPI REST API that runs the research pipeline.
The companion Next.js frontend lives in a separate sibling project,
`SalesIntelligenceAutomatorFrontend`.

---

## 1. What it does

Given a list of leads (one per line — company names, "Name – City ST", or URLs), the
pipeline:

1. **Intake** — normalizes each line (URL vs. company name), dedupes, strips location hints.
2. **Resolve** — for name-only leads, searches the web to find a likely homepage URL.
3. **Crawl + Extract** — fetches the homepage plus a small allow-list of high-signal pages
   (`/about`, `/services`, `/products`, `/contact`), strips out navigation, cookie banners,
   footers, and boilerplate, and de-duplicates repeated blocks across pages.
4. **Analyze** — sends the cleaned text to an LLM (Groq, OpenAI-compatible API) and gets back
   a strict, schema-validated **sales brief**:
   - Company Overview
   - Core Product or Service
   - Target Customer / Audience
   - **B2B Qualification** (Yes/No + reasoning)
   - **Three tailored Sales Questions**
   - Confidence level + evidence note

Each lead is processed independently and concurrently. A failing lead (unreachable site,
unresolvable name, LLM error) is marked `failed` with a reason — it never crashes the batch.

---

## 2. Project structure

```
SalesIntelligenceAutomator/
├── app/
│   ├── main.py                # FastAPI app + CORS setup
│   ├── api/
│   │   └── routes.py          # POST /api/leads, GET /api/leads, GET /api/leads/{id}, /health
│   ├── orchestrator.py        # runs the 4-stage pipeline per lead, with concurrency control
│   ├── pipeline/
│   │   ├── intake.py          # parse/normalize/dedupe raw lead text
│   │   ├── resolver.py        # company name -> homepage URL via search
│   │   ├── crawler.py         # httpx fast-path + Playwright fallback, crawl budget
│   │   ├── extractor.py       # trafilatura clean-text extraction + de-dupe + truncation
│   │   └── analyzer.py        # LLM call -> validated SalesBrief, retry on bad JSON
│   ├── llm/
│   │   ├── client.py          # LLMClient interface + GroqClient implementation
│   │   └── prompts.py         # system prompt, B2B rubric, JSON schema
│   ├── models/
│   │   ├── schemas.py         # Pydantic models: LeadInput, SalesBrief, LeadResult
│   │   └── db.py               # LeadRepository interface + SQLite implementation
│   └── core/
│       ├── config.py          # settings loaded from .env
│       └── cache.py           # on-disk cache: sha256(url+text) -> brief
├── tests/                      # unit tests + golden-output test (mocked LLM)
├── data/                       # sqlite db, on-disk cache, sample_leads.txt
├── .devcontainer/              # GitHub Codespaces config
├── docker-compose.yml          # scaling-path stub (Postgres/Redis seams)
├── requirements.txt
└── .env.example
```

---

## 3. Setup & run

### Requirements
- Python 3.11+
- A free [Groq API key](https://console.groq.com) (for the LLM analysis step)

### Install

```powershell
python -m venv .venv
.venv\Scripts\activate          # if blocked by execution policy, see note below
pip install -r requirements.txt
python -m playwright install --with-deps chromium
```

> **PowerShell execution policy:** if `.venv\Scripts\activate` is blocked, either run
> `Set-ExecutionPolicy -Scope Process RemoteSigned` for the session, or skip activation and
> prefix commands with `python -m` (e.g. `python -m uvicorn ...`, `python -m pytest`) — pip
> installs to your user site-packages and everything still works.

### Configure

```powershell
copy .env.example .env
```

`.env.example` is a blank template (no secrets, safe to commit). Edit your local `.env`
(gitignored) and set at minimum:
- `GROQ_API_KEY` — your Groq API key
- `CORS_ORIGINS` — the URL(s) the frontend runs on (e.g. `http://localhost:3000`)

See [Configuration](#5-configuration) below for what every setting does and its default if
left blank.

### Run

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

- API docs (Swagger UI): http://localhost:8000/docs
- Health check: http://localhost:8000/health

### Run tests

```powershell
python -m pytest
```

---

## 4. API

| Method | Path                | Description                                                  |
|--------|---------------------|---------------------------------------------------------------|
| GET    | `/health`           | Liveness check                                                |
| POST   | `/api/leads`        | Submit leads (multipart form: `leads` text field or `file` upload). Kicks off async processing, returns the created lead records immediately. |
| GET    | `/api/leads`        | List all lead records (for polling/table view)                |
| GET    | `/api/leads/export` | Download all lead records as an `.xlsx` workbook              |
| DELETE | `/api/leads`        | Clear all stored lead records                                  |
| GET    | `/api/leads/{id}`   | Get a single lead record (for detail view)                     |

Lead records progress through `status`: `pending` → `processing` → `done` / `failed`.

---

## 5. Configuration

All settings are read from `.env` (see `.env.example` for the full list of keys, and
`app/core/config.py` for what each one defaults to if left blank):

| Variable | Purpose | Default if blank |
|---|---|---|
| `GROQ_API_KEY` | Groq API key (required for analysis) | — |
| `LLM_PROVIDER` | LLM backend | `groq` |
| `GROQ_BASE_URL` | Groq's OpenAI-compatible endpoint | `https://api.groq.com/openai/v1` |
| `ANALYSIS_MODEL` | Model for the final sales brief | `llama-3.3-70b-versatile` |
| `FILTER_MODEL` | Reserved for cheap filtering/cleanup calls | `llama-3.1-8b-instant` |
| `MAX_PAGES` | Max pages crawled per lead | `4` |
| `CHAR_BUDGET` | Max characters of extracted text sent to the LLM | `7000` |
| `PER_PAGE_CHAR_CAP` | Max HTML characters kept per fetched page | `40000` |
| `REQUEST_TIMEOUT` | HTTP/crawl timeout (seconds) | `10` |
| `MAX_CONCURRENT_LEADS` | Concurrent leads processed at once | `4` |
| `DB_PATH` | SQLite database file | `data/sales_intel.db` |
| `CACHE_PATH` | On-disk LLM-response cache file | `data/cache.json` |
| `CORS_ORIGINS` | Comma-separated origins allowed to call the API | `http://localhost:3000` |

> Groq model IDs change over time — verify `ANALYSIS_MODEL`/`FILTER_MODEL` against Groq's
> live model list if analysis calls start failing with a "model not found" error.

---

## 6. Design Notes

**Architecture & tool choices.** Four single-responsibility pipeline stages (intake → resolve
→ crawl/extract → analyze) sit behind a FastAPI REST API. Python was chosen for its scraping
and LLM ecosystem. **Playwright** (over Selenium) for async-native browser automation with
auto-waiting and clean install in Codespaces — but the crawler tries a cheap `httpx` static
fetch first and only escalates to headless Chromium when a page is JS-rendered or yields too
little text. **trafilatura** (with a `readability-lxml` fallback) strips navigation, cookie
banners, footers, and boilerplate from raw HTML, which is the single biggest token-efficiency
win — it turns 100k+ tokens of markup into a few hundred tokens of clean body text before
anything is sent to the LLM. **Groq** provides fast, free-tier access to open-source models
(Llama 3.x), abstracted behind a single `LLMClient` interface so the provider can change via
config without touching pipeline code. Storage uses SQLite behind a `LeadRepository`
interface so Postgres/Supabase can drop in later without touching business logic.

**Edge cases.** Leads arrive imperfect — bare company names with no URL, dead domains,
JS-only pages, thin content. Name-only leads are resolved to a homepage via a plain search
call (`resolver.py`), with directory/social sites (Facebook, Yelp, LinkedIn, etc.) filtered
out of candidates. Unreachable sites raise a typed `CrawlError` and the lead is marked
`failed` with a reason, never crashing the batch — each lead is processed in isolation under
an `asyncio.Semaphore`. When extracted text is too thin to be useful, the analyzer skips the
LLM call entirely and returns a low-confidence brief with `"Unknown"` fields and
`b2b_qualified=false`, rather than spending tokens guessing.

**LLM reliability & token efficiency.** Output is constrained via Groq JSON mode plus a
Pydantic schema (`SalesBrief`) — the five required fields are always present and correctly
typed. Temperature is `0.1` for repeatable results. The system prompt embeds a single,
editable **B2B rubric**: qualified only if the company primarily sells to other businesses;
local consumer home-services (roofing, lawn care, plumbing, etc.) are B2C unless the page
shows a clear commercial/contractor/wholesale offering. If the LLM's JSON fails schema
validation, the pipeline re-prompts once with the validation error before marking the lead
`failed`. Token use is kept low via the extraction step, a per-page HTML cap, a 4-page crawl
budget, a 7k-character total budget with priority ordering (about/services first),
cross-page de-duplication of repeated blocks, and an on-disk cache keyed on
`sha256(resolved_url + extracted_text)` so re-running the same lead costs zero additional
tokens.

**What I'd improve with more time.** Move `BackgroundTasks` to a Redis-backed worker queue
(RQ/Celery) and swap SQLite for Postgres/Supabase for real concurrency — both seams are
already abstracted (`LeadRepository`, `docker-compose.yml` stub). Add an evaluation harness
that scores briefs against a labeled set to validate the B2B rubric and confidence
calibration. Use a richer search provider (e.g. Exa) for name→URL resolution instead of a
plain HTML search-results scrape. Add a CRM-integration point so a `done` brief can be POSTed
to a lead record automatically.
