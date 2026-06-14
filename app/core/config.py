"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Central configuration object. Read once at import time."""

    llm_provider: str = os.getenv("LLM_PROVIDER", "groq")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_base_url: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

    # Verify these against Groq's live model list at deploy time; names move over time.
    analysis_model: str = os.getenv("ANALYSIS_MODEL", "llama-3.3-70b-versatile")
    filter_model: str = os.getenv("FILTER_MODEL", "llama-3.1-8b-instant")

    max_pages: int = int(os.getenv("MAX_PAGES", "4"))
    char_budget: int = int(os.getenv("CHAR_BUDGET", "7000"))
    # Bounds raw HTML kept per page. Must be large: modern rendered pages put
    # the real body content tens of thousands of chars in, after the <head>
    # and inline scripts. char_budget (above) is what actually limits how much
    # text reaches the LLM, so this just needs to be big enough to not truncate
    # the body. Raw HTML is transient (never persisted), so a high cap is cheap.
    per_page_char_cap: int = int(os.getenv("PER_PAGE_CHAR_CAP", "200000"))

    db_path: str = os.getenv("DB_PATH", os.path.join("data", "sales_intel.db"))
    cache_path: str = os.getenv("CACHE_PATH", os.path.join("data", "cache.json"))

    request_timeout: float = float(os.getenv("REQUEST_TIMEOUT", "10"))
    max_concurrent_leads: int = int(os.getenv("MAX_CONCURRENT_LEADS", "4"))

    # Search backend for name->URL resolution and the snippet fallback.
    # Tavily/Brave are used when a key is present (both are reliable and have
    # free tiers); otherwise we scrape DuckDuckGo, which works but gets
    # rate-limited and bot-challenged, especially from datacenter IPs like
    # Render's. Tavily is checked first since it's the recommended default.
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    brave_api_key: str = os.getenv("BRAVE_API_KEY", "")

    # Comma-separated list of frontend origins allowed to call this API,
    # e.g. "http://localhost:3000,http://localhost:3001".
    cors_origins: list[str] = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")


settings = Settings()
