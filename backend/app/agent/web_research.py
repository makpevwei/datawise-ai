"""Web research: pluggable search across whichever provider(s) have a
configured key -- none required. Tried in a fixed priority order (Tavily,
Exa, Firecrawl, SerpAPI, Google CSE); the first configured provider that
returns successfully is used for a given query. Every HTTP call respects
SEARCH_TIMEOUT. Per-question call/query budgets (MAX_RESEARCH_QUERIES,
MAX_RESEARCH_TOOL_CALLS, MAX_RESEARCH_SOURCES) are enforced by the
web_research tool in app/agent/tools.py, not here -- this module just
performs one bounded search.
"""

from dataclasses import dataclass

import httpx

from app.ai.errors import redact_secrets
from app.config import Settings


@dataclass
class WebResult:
    title: str
    url: str
    snippet: str
    provider: str


class WebResearchNotConfiguredError(Exception):
    """Raised when no web search provider has a configured key."""


class WebResearchError(Exception):
    """Every configured provider's search call failed."""


def _raise_for_status(resp: httpx.Response, provider: str) -> None:
    """Deliberately does NOT use httpx's own raise_for_status(): that
    formats its exception message from resp.request.url, which for
    SerpAPI/Google CSE includes the API key as a query parameter --
    exactly the credential leak this function exists to prevent. This
    raises a clean, credential-free message instead."""
    if resp.status_code >= 400:
        raise WebResearchError(f"{provider} search failed with HTTP {resp.status_code}.")


def _search_tavily(query: str, api_key: str, max_results: int, timeout: float) -> list[WebResult]:
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": query, "max_results": max_results},
        timeout=timeout,
    )
    _raise_for_status(resp, "tavily")
    data = resp.json()
    return [
        WebResult(title=r.get("title") or "", url=r.get("url") or "", snippet=(r.get("content") or "")[:500], provider="tavily")
        for r in data.get("results", [])
    ]


def _search_exa(query: str, api_key: str, max_results: int, timeout: float) -> list[WebResult]:
    resp = httpx.post(
        "https://api.exa.ai/search",
        headers={"x-api-key": api_key},
        json={"query": query, "numResults": max_results, "contents": {"text": True}},
        timeout=timeout,
    )
    _raise_for_status(resp, "exa")
    data = resp.json()
    return [
        WebResult(title=r.get("title") or "", url=r.get("url") or "", snippet=(r.get("text") or "")[:500], provider="exa")
        for r in data.get("results", [])
    ]


def _search_firecrawl(query: str, api_key: str, max_results: int, timeout: float) -> list[WebResult]:
    resp = httpx.post(
        "https://api.firecrawl.dev/v1/search",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"query": query, "limit": max_results},
        timeout=timeout,
    )
    _raise_for_status(resp, "firecrawl")
    data = resp.json()
    return [
        WebResult(
            title=r.get("title") or "", url=r.get("url") or "",
            snippet=(r.get("description") or r.get("markdown") or "")[:500], provider="firecrawl",
        )
        for r in data.get("data", [])
    ]


def _search_serpapi(query: str, api_key: str, max_results: int, timeout: float) -> list[WebResult]:
    resp = httpx.get(
        "https://serpapi.com/search.json",
        params={"q": query, "api_key": api_key, "num": max_results, "engine": "google"},
        timeout=timeout,
    )
    _raise_for_status(resp, "serpapi")
    data = resp.json()
    return [
        WebResult(title=r.get("title") or "", url=r.get("link") or "", snippet=(r.get("snippet") or "")[:500], provider="serpapi")
        for r in data.get("organic_results", [])[:max_results]
    ]


def _search_google_cse(query: str, api_key: str, cse_id: str, max_results: int, timeout: float) -> list[WebResult]:
    resp = httpx.get(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": api_key, "cx": cse_id, "q": query, "num": min(max_results, 10)},
        timeout=timeout,
    )
    _raise_for_status(resp, "google_cse")
    data = resp.json()
    return [
        WebResult(title=r.get("title") or "", url=r.get("link") or "", snippet=(r.get("snippet") or "")[:500], provider="google_cse")
        for r in data.get("items", [])
    ]


def search_web(query: str, settings: Settings, max_results: int | None = None) -> list[WebResult]:
    """Tries configured providers in priority order; returns the first
    successful provider's results. Raises WebResearchNotConfiguredError if
    no provider is configured, WebResearchError if every configured
    provider's call failed."""
    max_results = max_results or settings.max_research_sources
    timeout = settings.search_timeout

    attempts: list[tuple[str, callable]] = []
    if settings.tavily_api_key:
        attempts.append(("tavily", lambda: _search_tavily(query, settings.tavily_api_key, max_results, timeout)))
    if settings.exa_api_key:
        attempts.append(("exa", lambda: _search_exa(query, settings.exa_api_key, max_results, timeout)))
    if settings.firecrawl_api_key:
        attempts.append(("firecrawl", lambda: _search_firecrawl(query, settings.firecrawl_api_key, max_results, timeout)))
    if settings.serpapi_api_key:
        attempts.append(("serpapi", lambda: _search_serpapi(query, settings.serpapi_api_key, max_results, timeout)))
    if settings.google_cse_id and settings.google_cse_api_key:
        attempts.append((
            "google_cse",
            lambda: _search_google_cse(query, settings.google_cse_api_key, settings.google_cse_id, max_results, timeout),
        ))

    if not attempts:
        raise WebResearchNotConfiguredError("No web research provider (Tavily/Exa/Firecrawl/SerpAPI/Google CSE) is configured.")

    last_error: str | None = None
    for _name, fn in attempts:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 -- try the next configured provider
            last_error = redact_secrets(str(exc))
            continue

    raise WebResearchError(f"All configured web research providers failed. Last error: {last_error}")
