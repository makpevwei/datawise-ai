"""Agentic RAG -- document ingestion (PDF/DOCX/PPTX/TXT/MD) and retrieval.

Upload -> extract -> clean -> chunk -> index -> retrieve. Each chunk keeps
type-appropriate source metadata (page/slide/heading/line) so every
document-grounded claim can cite exactly where it came from.
"""
