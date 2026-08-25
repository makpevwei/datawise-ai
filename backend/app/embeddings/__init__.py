"""Embeddings for document RAG retrieval (app/documents/store.py).

Fully optional: if no embedder can be constructed (model download blocked,
misconfigured provider, missing OpenAI key when embedding_provider=openai),
retrieval falls back to the TF-IDF path that already existed before Phase
4 -- RAG never becomes unavailable just because embeddings aren't.
"""
