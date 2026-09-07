"""Live routing tests for the GENERAL_KNOWLEDGE route.

Two specific cases from the task specification:
1. A genuinely off-topic question routes to GENERAL_KNOWLEDGE (not DATA_ONLY).
2. A borderline business-adjacent question does NOT slip into GENERAL_KNOWLEDGE.

Each test runs the LLM router 5 times and requires a supermajority (≥4/5) to
account for non-determinism at temperature=0. All 5 results are printed so
the output is a verifiable record, not just a pass/fail.

Requires a live LLM key (OPENAI_API_KEY, GEMINI_API_KEY, GROQ_API_KEY, or
OPENROUTER_API_KEY) -- skipped if none is set.

Run with:
    .venv/bin/python -m pytest tests/test_general_knowledge_routing_live.py -v -s
"""

import pytest

from app.agent.graph import ROUTE_TOOLS, _llm_route
from app.ai.gateway import LLMGateway
from app.ai.gemini_provider import GeminiProvider
from app.ai.groq_provider import GroqProvider
from app.ai.openai_provider import OpenAIProvider
from app.ai.openrouter_provider import OpenRouterProvider
from app.config import get_settings


def _make_gateway() -> "LLMGateway | None":
    """Build a real LLM gateway from whichever keys are configured."""
    settings = get_settings()
    providers = []
    if settings.openai_api_key:
        providers.append(OpenAIProvider(
            api_key=settings.openai_api_key, model=settings.openai_model,
            timeout=settings.llm_timeout, temperature=settings.temperature,
        ))
    if settings.gemini_api_key:
        providers.append(GeminiProvider(
            api_key=settings.gemini_api_key, model=settings.gemini_model,
            timeout=settings.llm_timeout, temperature=settings.temperature,
        ))
    if settings.groq_api_key:
        providers.append(GroqProvider(
            api_key=settings.groq_api_key, model=settings.groq_model,
            timeout=settings.llm_timeout, temperature=settings.temperature,
        ))
    if settings.openrouter_api_key:
        providers.append(OpenRouterProvider(
            api_key=settings.openrouter_api_key, model=settings.openrouter_model,
            base_url=settings.openrouter_base_url, timeout=settings.llm_timeout,
            temperature=settings.temperature,
        ))
    if not providers:
        return None
    return LLMGateway(providers=providers, max_retries=1)


def _any_llm_configured() -> bool:
    s = get_settings()
    return bool(s.openai_api_key or s.gemini_api_key or s.groq_api_key or s.openrouter_api_key)


RUNS = 5
PASS_THRESHOLD = 4  # ≥4/5 required


@pytest.mark.live
@pytest.mark.skipif(not _any_llm_configured(), reason="no LLM API key configured")
def test_genuinely_off_topic_question_routes_to_general_knowledge():
    """'Who is the president of Nigeria?' is a pure general-world-knowledge
    fact with no connection to business data or uploaded files.
    Expected: GENERAL_KNOWLEDGE on all 5 runs (threshold: ≥4/5)."""
    question = "Who is the president of Nigeria?"
    llm = _make_gateway()
    assert llm is not None

    results = []
    for i in range(RUNS):
        route = _llm_route(llm, question, has_datasets=True, has_documents=False, has_web=False)
        results.append(route)
        print(f"  Run {i+1}/5: {route}")

    gk_count = sum(1 for r in results if r == "GENERAL_KNOWLEDGE")
    print(f"  GENERAL_KNOWLEDGE: {gk_count}/{RUNS}  (threshold: ≥{PASS_THRESHOLD})")
    print(f"  Full results: {results}")

    assert gk_count >= PASS_THRESHOLD, (
        f"Expected GENERAL_KNOWLEDGE ≥{PASS_THRESHOLD}/{RUNS} times, got {gk_count}. "
        f"Full results: {results}"
    )


@pytest.mark.live
@pytest.mark.skipif(not _any_llm_configured(), reason="no LLM API key configured")
def test_borderline_business_question_does_not_slip_into_general_knowledge():
    """'What is gross margin and how do I calculate it?' is a conceptual
    business question -- it looks general but is directly relevant to any
    business dataset. The router must stay conservative and route to DATA_ONLY
    (or another data route), never GENERAL_KNOWLEDGE.
    Expected: NOT GENERAL_KNOWLEDGE on all 5 runs (threshold: ≥4/5)."""
    question = "What is gross margin and how do I calculate it?"
    llm = _make_gateway()
    assert llm is not None

    results = []
    for i in range(RUNS):
        route = _llm_route(llm, question, has_datasets=True, has_documents=False, has_web=False)
        results.append(route)
        print(f"  Run {i+1}/5: {route}")

    not_gk_count = sum(1 for r in results if r != "GENERAL_KNOWLEDGE")
    print(f"  Not GENERAL_KNOWLEDGE: {not_gk_count}/{RUNS}  (threshold: ≥{PASS_THRESHOLD})")
    print(f"  Full results: {results}")

    assert not_gk_count >= PASS_THRESHOLD, (
        f"Expected NOT GENERAL_KNOWLEDGE ≥{PASS_THRESHOLD}/{RUNS} times, got {not_gk_count}. "
        f"Full results: {results}"
    )
    # Additionally assert it goes to a real data route, not None/heuristic
    data_routes = {k for k in ROUTE_TOOLS if k not in ("GENERAL_KNOWLEDGE",)}
    data_route_count = sum(1 for r in results if r in data_routes)
    print(f"  Routed to a real data/doc route: {data_route_count}/{RUNS}")
    assert data_route_count >= PASS_THRESHOLD, (
        f"Expected a real data/doc route ≥{PASS_THRESHOLD}/{RUNS} times, got {data_route_count}. "
        f"Full results: {results}"
    )
