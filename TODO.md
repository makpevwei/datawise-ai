# TODO

Roughly priority-ordered. Not a sprint plan — a running list so nothing
outstanding gets lost between sessions.

## High priority — security, cost, reliability

- **Payment/billing integration.** There is currently no way for a real
  user to pay for anything — sign-up is free, unlimited (aside from the
  new rate limits), forever. If real customers/investors are the goal,
  this is the single biggest functional gap. (Stripe is the standard
  choice; not yet evaluated.)
- **Rate limiting is in-memory, correct only while Cloud Run runs a single
  instance.** Currently true (min-instances=1, low traffic), but if this
  service is ever scaled to multiple concurrent instances, each instance
  enforces its own separate counter — the effective limit becomes roughly
  (configured limit × instance count), not a hard violation, but a real
  gap. Needs a shared backend (Redis, e.g. Upstash's free tier) before
  real scale.
- **Branch protection on `main` is blocked, not just undone.** GitHub
  Free doesn't support branch protection on a private repo at all — it's
  a paid-plan (Pro, ~$4/month) feature there, or free if the repo is
  public. Deliberately staying private + free for now (see the "Domain
  ownership" decision made earlier). Until this is revisited, a direct
  push straight to `main` — CI red or not — still reaches Vercel's
  production deploy unopposed. (The Cloud Run side is *not* exposed to
  this specific gap: its own CI-triggered deploy job only runs after
  `backend`+`frontend` CI pass on `main`, independent of branch
  protection — see below.) Revisit by either paying for Pro or accepting
  the tradeoff of a public repo.
  - DONE (2026-08-30): CI-triggered Cloud Run deploy via Workload Identity
    Federation, replacing manual `gcloud run deploy` entirely — push to
    `main` → CI passes → automatic deploy, no long-lived GCP key stored
    anywhere. Full writeup in `docs/deploy-pipeline.md`.
- **Password reset emails send from a personal Gmail address.** Display
  name now reads "DataWise AI," but the underlying address is still
  personal. Real fix: verify a custom domain (with Resend, or Gmail
  Workspace) once one exists — ties into the domain/branding item below.
- **No custom domain.** Currently on `*.vercel.app` / `*.run.app`
  subdomains. Matters for investor credibility and would also solve the
  email-sender-address gap above in one move.
- **No backup/restore posture documented** for the production Postgres
  database (on Render) now that it holds real user accounts and data.
  Needs verifying what Render actually provides and whether it's enough.
- **JWT tokens are valid for 7 days with no revocation.** `/auth/logout`
  is client-side only (documented in the code) — there's no way to force
  a specific token invalid before its natural expiry (e.g. if an account
  is compromised). A token-blocklist table would close this; deliberately
  not built yet (noted as future work when the auth endpoints were first
  written).

## Connected sources (Google Drive/Sheets)

- **RAG quality-bar test not run yet.** The connector itself (OAuth,
  sync, per-tenant isolation, dual-layer read-only enforcement) is built,
  tested, and deployed, but the ~12-15 question accuracy test against a
  real connected Sheet/Drive doc (target ≥90%, reported honestly either
  way) needs a live connected Google account to run against — blocked on
  someone actually connecting one in the deployed app. Do this before
  calling the connector done, not just shipped.
- **OAuth consent screen is in Testing, not Published.** Fine for the
  founder's own account (added as a test user) against both local and
  the deployed URL. Before any real company that isn't on the test-user
  list (max 100) can connect, this needs Google's verification process
  for the two sensitive scopes (`drive.readonly`, `spreadsheets.readonly`)
  — a privacy policy URL and days of review lead time. Plan for this
  before onboarding company #1.
- **Dataset/Document versioning logic is duplicated, not shared.** The
  `Dataset` model's own docstring (`app/db/models.py`) points at
  `app/domains/versioning.py` for the version-chaining logic — that
  module doesn't exist. The real logic lives privately inside
  `app/api/datasets.py`/`documents.py`'s route handlers, and
  `app/integrations/service.py` now duplicates the same pattern a third
  time rather than importing a shared implementation (judged lower-risk
  than refactoring a tested, production upload path under this phase's
  time constraints). Real fix: extract into an actual
  `app/upload/versioning.py`, fix the stale docstring, and have all three
  call sites use it.
- **On-demand sync only — no scheduled/background auto-sync.** A
  connected Sheet only re-pulls when the user clicks "Sync Now." Fine for
  proving the pattern; a real product needs this to happen automatically
  (cron/worker process, a genuine new infra addition — new failure mode,
  not just new code).
- **No Google Picker widget.** The file/sheet selector is a plain
  backend-driven checkbox list (`GET /integrations/{id}/browse`), not
  Google's own Picker JS component. Functionally complete, but Picker
  would be the nicer, more familiar UX — purely visual upgrade, not
  blocking.
- **ERPNext connector remains fully deferred, by design** — no
  ERPNext-specific code exists anywhere in this codebase. The
  `Integration`/`ConnectedItem` data model is already generic (`provider`
  is a plain string, not an enum) specifically so ERPNext can reuse it
  later without a migration, once the Drive/Sheets pattern has proven
  itself with a real connected account.

## Medium priority — code health

- **LLM router now always pays one extra LLM round-trip** per question (the
  old skip-when-unambiguous optimisation was removed to make GENERAL_KNOWLEDGE
  always reachable). For workspaces with only one resource type (datasets only,
  no docs, no web) this is a new, consistent ~200–400ms overhead per question
  that didn't exist before. Worth revisiting if latency becomes a concern:
  a fast deterministic pre-filter (e.g. regex/keyword list of known off-topic
  patterns) could restore the fast path for the unambiguous cases without
  removing GENERAL_KNOWLEDGE support.

- **LLM-driven KPI column classification (sum/mean/exclude) only covers
  the single-dataset KPI cards** (`app/analysis/kpi_discovery.py`'s
  `discover_kpis`), not the Management Dashboard's chart selection
  (`app/analysis/dashboard_charts.py`'s `discover_dashboard_charts`/
  `discover_cross_dataset_charts`) — that path only has the deterministic
  keyword heuristic to work with, since threading an LLM provider through
  its whole call chain (used from multiple API endpoints, some
  unauthenticated-adjacent) is a bigger change than fit in the phase that
  found this gap. Concretely: a per-entity score/rating column with a
  name the deterministic hint list hasn't been extended for yet (unlike
  "age"/"score"/"rating", already covered) can still show up summed on a
  dashboard chart even though the same column would correctly get MEAN on
  a KPI card. Real fix: extend chart discovery to accept an optional LLM
  provider the same way `discover_kpis` already does.
- **Pre-existing test-order flakiness** (separate from the item below).
  Running the full suite locally twice produced two different sets of
  failures both times (report/email tests one run, nothing the next),
  while every individually-failing test passed cleanly in isolation.
  Likely root cause: many test files share a module-level `TestClient(app)`
  and mutate `app.dependency_overrides` directly rather than through an
  isolated per-test fixture, so one test's leftover state can leak into
  another depending on execution order. `pytest --reruns 1` in CI is a
  stopgap, not a fix. Real fix: a proper per-test client fixture with
  guaranteed teardown.
- **3 agent/session tests fail deterministically in CI, every run, but
  pass every time locally** (`test_ask_with_fake_llm_runs_full_loop`,
  `test_ask_with_dataset_ids_scopes_the_agent_to_only_those_datasets`,
  `test_ask_creates_a_session_and_it_can_be_restored` -- currently marked
  `xfail` in the test files so CI stays green without hiding the issue).
  Symptom: the agent's main tool-calling turn gets skipped -- routing
  goes straight to the synthesis/formatting call, one LLM turn short of
  what the test scripts expect. Reruns don't help (it's not random).
  Ruled out: a langgraph/langchain-core version mismatch (pinned
  identically in the lockfile and the local venv). Not investigated
  further yet -- most likely lead is CI's Postgres starting genuinely
  empty on every run vs. a local dev database with a lot of accumulated
  history from repeated manual testing, if something in session/message
  lookup depends on row state without an explicit tiebreaker. Needs a
  real debugging session, not a guess.

- **mypy: 51 findings, currently advisory-only** (doesn't block CI). ~39
  pre-existed the CI-gate phase; the rest came from this phase's own rate
  limiting code (mostly `Depends`-related type mismatches slowapi's
  decorator introduces, plus pre-existing `ScopedDatasetStore` vs
  `DatasetStore` structural typing gaps). Needs a dedicated cleanup pass
  before mypy can be a real blocking gate.
- **9 files carry lint exceptions** for pre-existing findings (unused
  variables, bare except-pass, a few other minor issues), deliberately
  left alone rather than editing unrelated code while adding the lint
  gate itself: `app/analysis/engine.py`, `app/analysis/kpi_discovery.py`,
  `app/agent/planner.py`, `app/agent/verification.py`,
  `app/ai/anthropic_provider.py`, `app/ai/openai_provider.py`,
  `app/documents/store.py`, `app/profiling/type_inference.py`,
  `app/semantic/store.py`. See the `ignore` list in `backend/pyproject.toml`
  for the exact rule codes.
- **No load/scale testing done.** The stated goal is dozens of users to
  millions without a rewrite; nothing has actually been tested under real
  concurrent load yet — Cloud Run's autoscaling behavior, Postgres
  connection pool limits, and the in-memory rate limiter's multi-instance
  gap (above) all matter here.

## Lower priority

- **ScatterChart / PointMapChart visual polish** — hover transitions and
  tooltip polish deferred; lower priority, not blocking. Pick up when the
  rest of the chart work is needed.
- Frontend accessibility (a11y) audit — not done yet.
- Cost monitoring: an OpenAI spending cap is set (done, earlier session) —
  worth periodically re-checking it's still current as usage grows.
