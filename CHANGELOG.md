# Changelog

Plain-English record of what's shipped, newest first. No version numbers yet
(pre-1.0, deploys are continuous rather than tagged releases) — entries are
grouped by date instead.

## 2026-09-07 — Chart and UI component visual polish

- **BarChart**: group-hover label/value colour fade, opacity dim (0.45) on
  non-hovered bars, `shadow-sm → shadow-md` lift on hover.
- **LineChart**: area gradient fill (`stopOpacity` 0.15→0.01), hover circle
  grows r=3.5→6 with drop-shadow, dark tooltip box with formatted value.
- **DonutChart**: hovered slice translates outward along its midpoint angle
  ("lifted" effect consistent with BarChart's shadow lift), `drop-shadow`
  filter, `opacity` + `transform` transitions on all paths. Center label
  shows hovered slice's percentage (large, in the slice's own colour) and
  truncated name (small, secondary) while hovering. Legend dot scales
  1→1.4 and non-hovered rows fade to 0.45 opacity.
- **GroupedBarChart**: `group-hover` label fade (text-secondary→text-primary),
  `transition-all` + `shadow-sm → shadow-md` on each segment bar, opacity
  dim (0.45) on non-hovered segments — same visual language as BarChart.
- **EmptyState**: `border-dashed`, brand-subtle icon container, `py-20`,
  `leading-relaxed` description.
- **ErrorBanner**: left-border accent (`border-l-4`), `IconAlertTriangle`,
  `shadow-sm`, `leading-relaxed`.
- **Spinner**: split border colours (text-muted ring + brand top arc).
- **StatCard / KPI cards**: `shadow-sm → shadow-md` on hover, `compact`
  prop for dense grids, `line-clamp-2` labels, tap-to-expand with
  "Tap for exact value / Tap to collapse" hint text.
- All 92 frontend tests pass; ScatterChart and PointMapChart left as-is
  (lower priority, not blocking).

## 2026-09-02 — Google Drive/Sheets connector (read-only)

- **First "connected source" integration**: a company can now connect
  Google Drive and Google Sheets, read-only, via standard Google OAuth.
  Deliberately built as a generic pattern (not hardcoded to Google) so a
  future connector — ERPNext, explicitly deferred this phase, and others
  — can reuse the same `Integration`/`ConnectedItem` data model and the
  same sync path into `Dataset`/`Document` without rework.
- **Read-only enforced twice, independently**: only `drive.readonly` and
  `spreadsheets.readonly` scopes are ever requested (Google itself
  rejects a write call at the protocol level before this code is even
  involved); separately, the one module allowed to call Drive/Sheets data
  APIs is covered by a test that parses its own source and fails the
  build if a write-method name ever appears in it — not just a comment.
- **No new agent/RAG code needed**: a synced Sheet becomes a normal
  `Dataset` row, a synced Drive doc a normal `Document` row, through the
  same ingestion pipeline uploads already use — so the entire existing
  agent, citation, verification, and per-user isolation layer already
  works on connected data, unmodified.
- Refresh tokens encrypted at rest (Fernet) — the first encryption-at-rest
  primitive in this codebase. Standard versioning (new version on change,
  nothing hard-deleted) via the source's own last-modified timestamp.
- New Settings → Integrations tab (connect/browse/select/sync/disconnect)
  and a `source` badge on My Data's dataset/document tables.
- Production database migrations are now automated end-to-end: the
  deploy job runs `alembic upgrade head` against the real production
  Postgres before every Cloud Run deploy — previously only ran against
  CI's ephemeral test database, a real gap this phase closed.
- **Still pending**: the RAG accuracy test against a live connected
  account (target ≥90%, not yet run — needs someone to actually connect
  one), and Google's OAuth app verification (needed before any company
  outside the test-user list can connect; consent screen intentionally
  left in Testing for now). See TODO.md.

## 2026-08-30 — Rate limiting, CI gate, CI-triggered deploy

- **Rate limiting** on every auth endpoint (register, login, forgot-password,
  reset-password) and every endpoint that calls an LLM provider (`/agent/ask`,
  `/documents/upload`) — closes a real, live cost/abuse exposure (open
  sign-up sitting in front of a metered OpenAI key, brute-force exposure on
  login). See the phase summary for exact limits and reasoning.
- **CI pipeline** (GitHub Actions): lint (ruff), a real `next build`, and
  the test suites, all blocking, running against a real ephemeral
  Postgres service container for the backend; type-check (mypy)
  advisory-only for now, since the codebase has no prior type-checking
  history.
- **CI-triggered Cloud Run deploy**, replacing manual `gcloud run deploy`
  entirely: push to `main` → CI passes → automatic deploy, authenticated
  via Workload Identity Federation (no long-lived GCP service-account key
  stored anywhere). Full pipeline documented in `docs/deploy-pipeline.md`.
- **Branch protection on `main` evaluated, not enabled** — GitHub Free
  doesn't support it on a private repo at all (Pro-plan feature there).
  Deliberately staying private + free for now rather than pay or go
  public; a direct push to `main` can still reach Vercel unopposed until
  this is revisited. Tracked in TODO.md.

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
