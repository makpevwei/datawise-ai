"""Agentic layer: planner, explicit tools, verification, and memory.

Architecture: question -> planner (intent + tool selection) -> tools.py
(data analysis / RAG, always deterministic) -> verification.py (labels
every claim, never upgrades AI interpretation to a verified fact) ->
structured AgentAnswer. The deterministic engine in app/analysis,
app/profiling, app/relationships stays the sole source of numerical
truth; nothing here recomputes a business number independently.
"""
