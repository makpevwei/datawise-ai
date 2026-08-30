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
- **Wire CI into an actual deploy gate.** The CI pipeline (lint + tests,
  advisory type-check) runs on every push/PR right now, but nothing
  currently *blocks* on it — there's no branch protection on `main` and
  the team has been pushing directly to `main` all along. Two decisions
  needed:
  1. Turn on GitHub branch protection for `main` (require the CI check to
     pass) and switch to a PR-based workflow instead of direct pushes —
     this is what makes "Vercel doesn't deploy a broken build" true, since
     Vercel's production deploy triggers on a push to `main`.
  2. Backend deploy mechanism — recommended: move from manual
     `gcloud run deploy` to CI-triggered deploy via Workload Identity
     Federation (no long-lived GCP key sitting in GitHub Secrets). This
     would also sidestep the local-machine gcloud CLI flakiness that ate
     significant time this session (a stale metadata-detection cache file
     causing multi-minute hangs) — a clean GitHub Actions runner doesn't
     have that local state. Real setup work (~30-60 min), not done yet.
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

## Medium priority — code health

- **Pre-existing test-order flakiness.** Running the full suite locally
  twice produced two different sets of failures both times (agent/session
  tests one run, report/email tests the next), while every individually-
  failing test passed cleanly in isolation. Root cause: many test files
  share a module-level `TestClient(app)` and mutate `app.dependency_overrides`
  directly rather than through an isolated per-test fixture, so one test's
  leftover state can leak into another depending on execution order. CI
  currently works around this with `pytest --reruns 1` (a stopgap, not a
  fix) so a real, order-independent failure isn't masked by a flaky one.
  The real fix is restructuring the shared test client into a proper
  per-test fixture with guaranteed teardown.

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

- Frontend accessibility (a11y) audit — not done yet.
- Cost monitoring: an OpenAI spending cap is set (done, earlier session) —
  worth periodically re-checking it's still current as usage grows.
