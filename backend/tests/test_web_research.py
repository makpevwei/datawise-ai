"""Web research (app/agent/web_research.py) and the bounded web_research
tool (app/agent/tools.py). HTTP calls are mocked -- no real network here;
a small number of REAL calls happen separately (see the live suite)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.agent.tools import TOOLS, ResearchBudget, ToolContext, ToolExecutionError
from app.agent.web_research import WebResearchError, WebResearchNotConfiguredError, search_web
from app.config import Settings
from app.documents.store import DocumentStore
from app.semantic.store import DatasetStore


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _mock_response(json_body: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=MagicMock(), response=resp)
    return resp


def test_no_provider_configured_raises_not_configured():
    with pytest.raises(WebResearchNotConfiguredError):
        search_web("industry benchmark", _settings())


def test_tavily_used_when_configured():
    with patch("httpx.post") as mock_post:
        mock_post.return_value = _mock_response({"results": [{"title": "T", "url": "https://x.test", "content": "some content"}]})
        results = search_web("q", _settings(tavily_api_key="tvly-test"))
    assert len(results) == 1
    assert results[0].provider == "tavily"
    assert results[0].url == "https://x.test"


def test_provider_priority_tavily_before_exa():
    settings = _settings(tavily_api_key="tvly-test", exa_api_key="exa-test")
    with patch("httpx.post") as mock_post:
        mock_post.return_value = _mock_response({"results": [{"title": "T", "url": "https://x.test", "content": "c"}]})
        results = search_web("q", settings)
    assert results[0].provider == "tavily"
    # Only the first configured provider's endpoint was called.
    assert mock_post.call_args[0][0] == "https://api.tavily.com/search"


def test_falls_back_to_next_provider_when_first_fails():
    settings = _settings(tavily_api_key="tvly-test", exa_api_key="exa-test")
    with patch("httpx.post") as mock_post:
        mock_post.side_effect = [
            _mock_response({}, status_code=500),
            _mock_response({"results": [{"title": "E", "url": "https://y.test", "text": "content"}]}),
        ]
        results = search_web("q", settings)
    assert results[0].provider == "exa"


def test_all_providers_failing_raises_web_research_error():
    settings = _settings(tavily_api_key="tvly-test")
    with patch("httpx.post") as mock_post:
        mock_post.return_value = _mock_response({}, status_code=500)
        with pytest.raises(WebResearchError):
            search_web("q", settings)


def test_serpapi_uses_get_with_query_params():
    with patch("httpx.get") as mock_get:
        mock_get.return_value = _mock_response({"organic_results": [{"title": "S", "link": "https://s.test", "snippet": "snip"}]})
        results = search_web("q", _settings(serpapi_api_key="serp-test"))
    assert results[0].provider == "serpapi"
    assert mock_get.call_args.kwargs["params"]["q"] == "q"


def test_google_cse_requires_both_id_and_key():
    # Only the key set, no cse_id -- must not be treated as configured.
    with pytest.raises(WebResearchNotConfiguredError):
        search_web("q", _settings(google_cse_api_key="key-only"))


# -- The bounded web_research tool --------------------------------------------


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(
        dataset_store=DatasetStore(storage_dir=tmp_path / "d"),
        document_store=DocumentStore(storage_dir=tmp_path / "doc"),
        settings=_settings(tavily_api_key="tvly-test", max_research_sources=10),
        research_budget=ResearchBudget(max_queries=2, max_tool_calls=2),
    )


def test_web_research_tool_returns_results(ctx):
    with patch("httpx.post") as mock_post:
        mock_post.return_value = _mock_response({"results": [{"title": "T", "url": "https://x.test", "content": "c"}]})
        output = TOOLS["web_research"].handler({"query": "industry benchmark"}, ctx)
    assert output["results"][0]["url"] == "https://x.test"
    assert ctx.research_budget.queries_used == 1


def test_web_research_tool_enforces_call_budget(ctx):
    with patch("httpx.post") as mock_post:
        mock_post.return_value = _mock_response({"results": []})
        TOOLS["web_research"].handler({"query": "q1"}, ctx)
        TOOLS["web_research"].handler({"query": "q2"}, ctx)
        with pytest.raises(ToolExecutionError, match="limit"):
            TOOLS["web_research"].handler({"query": "q3"}, ctx)


def test_web_research_tool_without_context_settings_raises():
    ctx_no_settings = ToolContext(dataset_store=None, document_store=None)  # type: ignore[arg-type]
    with pytest.raises(ToolExecutionError):
        TOOLS["web_research"].handler({"query": "q"}, ctx_no_settings)


def test_web_research_tool_not_configured_is_a_tool_error_not_a_crash(tmp_path):
    ctx_unconfigured = ToolContext(
        dataset_store=DatasetStore(storage_dir=tmp_path / "d2"),
        document_store=DocumentStore(storage_dir=tmp_path / "doc2"),
        settings=_settings(),  # no provider keys
        research_budget=ResearchBudget(max_queries=5, max_tool_calls=5),
    )
    with pytest.raises(ToolExecutionError):
        TOOLS["web_research"].handler({"query": "q"}, ctx_unconfigured)
