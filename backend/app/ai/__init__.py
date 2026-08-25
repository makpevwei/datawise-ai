"""LLM provider abstraction and agent orchestration.

Everything under this package is optional at runtime: if no LLM is
configured, `get_llm_client()` returns None and callers must degrade to an
honest "AI features are not configured" response. The deterministic
DataWise engine (backend/app/analysis, profiling, relationships, ...)
never depends on this package.
"""
