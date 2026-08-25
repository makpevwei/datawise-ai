# Document embeddings: model choice and rationale

## Chosen model

`sentence-transformers/all-MiniLM-L6-v2`, served locally via LangChain's
`HuggingFaceEmbeddings` (`langchain-huggingface` + `sentence-transformers`),
CPU-only, no API key.

Configured via:

```
EMBEDDING_PROVIDER=huggingface
HUGGINGFACE_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

`EMBEDDING_PROVIDER=openai` remains available (`OPENAI_EMBEDDING_MODEL`,
default `text-embedding-3-small`) for anyone who explicitly wants it and
already has OpenAI credits, but it is never the default and DataWise's
document RAG works with zero embedding spend.

## Why this model

- **Free and local.** No API key, no per-call cost, no network dependency
  once the ~90MB model is cached locally (first run downloads it from the
  Hugging Face Hub; every run after that is fully offline).
- **CPU-friendly.** 6 transformer layers, 384-dimension output. Encoding a
  typical document chunk takes well under a second on CPU in this
  environment (see the empirical measurement below) -- no GPU required,
  which matters for a backend that otherwise has no GPU dependency anywhere
  else in the stack.
- **Small install footprint.** ~90MB model weights vs. multi-GB
  alternatives (e.g. larger E5/BGE models); keeps `uv sync` and container
  images lean.
- **Reasonable retrieval quality for business documents.** all-MiniLM-L6-v2
  is one of the most widely deployed general-purpose sentence embedding
  models precisely because it trades a small amount of top-tier accuracy
  (versus larger models on the MTEB leaderboard) for speed and size, and
  business-report prose (the actual content DataWise indexes -- management
  commentary, financial narrative, PDF/DOCX/PPTX/TXT/MD/PY text) is
  well within its training distribution. It was not benchmarked against
  every alternative for this project; it was selected as the well-established
  practical default the task specification itself suggested, and it is
  swappable via `HUGGINGFACE_EMBEDDING_MODEL` if a specific corpus later
  shows it underperforming.

## Environment constraint discovered during integration

This machine is an Intel Mac (x86_64). PyTorch dropped macOS x86_64 wheel
support after the 2.2.x series, and `transformers` (a `sentence-transformers`
dependency) requires `torch>=2.5` in its newest releases -- so the latest
`sentence-transformers`/`transformers` pairing cannot run here at all on
this architecture. Two pins were required to make the free local model work
on this development machine:

- `torch==2.2.2` (last version with an x86_64 macOS wheel)
- `sentence-transformers<4` (pulls a `transformers` version that still
  supports torch 2.2.x)
- `numpy<2` (torch 2.2.2's compiled C extensions target NumPy 1.x's ABI;
  without this pin, `tensor.numpy()` raises `RuntimeError: Numpy is not
  available` at inference time)

The `numpy<2` pin was verified not to break Phase 2/3's deterministic
analytics engine (pandas/pyarrow/scikit-learn) -- the full backend test
suite (255 tests) passes unchanged after the downgrade. On Apple Silicon or
Linux this constraint would not apply and newer pins could be used.

## Fallback behavior

Document retrieval (`app/documents/store.py`) always builds a TF-IDF
cosine-similarity index too (the original Phase 3 mechanism) as a safety
net. If no embedder can be constructed (model unavailable, misconfigured,
network blocked) or an embed call fails at retrieval time,
`app.embeddings.provider.get_embedder()` returns `None` / the failure is
caught, and retrieval transparently falls back to TF-IDF. RAG availability
never depends on the embedding model succeeding.

## Measured performance (this environment)

- First-time model download + load: ~208s (one-time, network-bound).
- Subsequent process starts (model cached locally): load is fast, no
  network call.
- Embedding a short chunk (a few sentences): well under 1 second.
- Per-chunk embeddings are cached in memory keyed by chunk id
  (`DocumentStore._chunk_embeddings`), so uploading an additional document
  only embeds its own new chunks, never re-embeds the existing corpus.
