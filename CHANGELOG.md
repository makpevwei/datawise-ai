# Changelog

Plain-English record of what's shipped, newest first. No version numbers yet
(pre-1.0, deploys are continuous rather than tagged releases) — entries are
grouped by date instead.

## 2026-08-30 — Rate limiting, CI gate

- **Rate limiting** on every auth endpoint (register, login, forgot-password,
  reset-password) and every endpoint that calls an LLM provider (`/agent/ask`,
  `/documents/upload`) — closes a real, live cost/abuse exposure (open
  sign-up sitting in front of a metered OpenAI key, brute-force exposure on
  login). See the phase summary for exact limits and reasoning.
- **CI pipeline** (GitHub Actions): lint (ruff) + tests, blocking; type-check
  (mypy) advisory-only for now, since the codebase has no prior
  type-checking history. Not yet wired to actually gate deploys — see
  TODO.md.

## 2026-08-28 — Password reset, dashboard fixes, Cloud Run migration

- **Self-service password reset**: forgot-password/reset-password endpoints
  and matching frontend pages, emailed via SMTP. Purely additive to the
  `users` table (two new nullable columns) — no existing account affected.
- **Demo account password** changed from `password` (a top-common-password
  that mobile browsers correctly flag as unsafe) to something still easy to
  type on a phone but not on breach lists.
- **Executive KPI Summary cards** made tap-to-expand (previously only a
  hover tooltip, which doesn't work on touch devices at all) — then
  re-sized down for the dense 6-up grid after the first pass made values
  truncate into unreadable dots.
- **Backend moved from Render to Google Cloud Run.** Render's free/Starter
  tiers cap a web service at 512MB RAM regardless of plan — too little for
  this app's baseline footprint (pandas/torch/sentence-transformers),
  causing uploads to silently crash the process under real use. Cloud Run
  allows configurable memory (currently 2GB) with a real free tier.
  Postgres itself stays on Render — only the web service moved.
- **Persistent file storage**: uploaded datasets/documents are stored in a
  Google Cloud Storage bucket mounted into the Cloud Run container, so they
  survive container restarts (Cloud Run's local disk is otherwise wiped on
  every scale-to-zero/cold start).
- **Fixed a real memory bug**: `DatasetStore` used to eagerly load every
  dataset from every user into memory on process start — unscoped, and
  growing more expensive with every restart as data accumulated. Now
  indexes lightweight metadata eagerly and loads each dataset's actual data
  only on first real access.
- **Added a database connection timeout** (10s) — there wasn't one before,
  so a stalled DB connection had no ceiling and could leave a request
  hanging indefinitely with zero response.

## 2026-08-27 — RAG grounding, embeddings persistence, auto-join dashboards

- **Document Q&A now checks uploaded documents before falling back to
  general knowledge** — previously a "what is X?"-shaped question could
  skip a relevant uploaded document entirely and answer from the model's
  own training instead, then present that as if it came from the user's
  data.
- **Fixed a severe RAG latency bug**: computed document-chunk embeddings
  were only cached in memory, so every process restart meant re-embedding
  every previously-uploaded document from scratch (multi-minute stalls).
  Now persisted to disk.
- **Automatic cross-dataset dashboard charts**: when two uploaded datasets
  share a relationship (e.g. a shared customer_id), the dashboard can now
  discover and chart insights that neither table could answer alone,
  without the user manually configuring a join.
- Repositioned the README for a real-business/investor audience rather than
  hackathon-specific framing.

## 2026-08-25 — Initial submission

- First working version: CSV/Excel/PDF upload, deterministic
  pandas-based analysis engine, agentic Q&A with tool-calling (Claude/GPT/
  Gemini/Groq, pluggable), document RAG, auto-generated executive
  dashboards, JWT auth with per-user data isolation, PDF report export.
