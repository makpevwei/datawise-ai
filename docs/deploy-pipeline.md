# Deploy Pipeline

How a code change actually reaches production, end to end.

## The flow

> **Branch protection is not currently enabled** — see the note at the end
> of this section. Steps 1-3 below describe the *intended* flow once it
> is; today, a push straight to `main` skips them entirely.

1. Work happens on a branch, opened as a PR into `main`. GitHub Actions'
   `backend` and `frontend` jobs (`.github/workflows/ci.yml`) run
   automatically: lint, a real `next build`, type-checking, and the test
   suites (backend against a real ephemeral Postgres service container).
2. Branch protection requires both jobs to pass before the PR's merge
   button unlocks. A red CI blocks the merge — there is no bypass, not
   even for repo admins.
3. Once merged, `main` gets the push. Two things happen automatically,
   with no manual command:
   - **Vercel** deploys the frontend from its own GitHub integration
     (unrelated to this repo's CI setup — Vercel watches pushes to `main`
     directly). Since nothing broken can reach `main` per step 2, this is
     never a broken build.
   - **GitHub Actions' `deploy` job** runs, but only after `backend` and
     `frontend` succeed again on `main` itself (`needs: [backend,
     frontend]`) and only on an actual push to `main` — not on PRs, so a
     PR from a fork can never trigger a deploy. It first runs `alembic
     upgrade head` against the real production database (Render Postgres
     — see below) using the same `DATABASE_URL` secret, so schema exists
     before any new code can serve traffic against it, then authenticates
     to Google Cloud via Workload Identity Federation and runs `gcloud run
     deploy` against Cloud Run.

**Why branch protection isn't on yet:** GitHub blocks branch protection on
a private repo below the paid Pro plan. Given this repo was deliberately
made private (to keep the source code from being publicly visible), the
choice for now is to stay private and free rather than pay for Pro or go
public — see TODO.md. Until that's revisited, the `deploy` job's own
`needs: [backend, frontend]` still means Cloud Run only ever deploys code
that passed CI (that part doesn't depend on branch protection at all) —
what's *not* yet guaranteed is that a broken push can't reach `main` and
Vercel in the first place.

No human ever runs `gcloud run deploy` by hand anymore.

## Workload Identity Federation (why there's no GCP key in GitHub)

The old approach for letting a CI system deploy to GCP was minting a
service-account JSON key and pasting it into a CI secret — a long-lived
credential that, if it ever leaked, works from anywhere, forever, until
someone notices and revokes it.

Workload Identity Federation (WIF) removes that key entirely. Instead:

- GitHub Actions already gives every job a short-lived, workflow-scoped
  OIDC token proving "this is a run of `makpevwei/datawise-ai`."
- GCP has a **Workload Identity Pool** (`github-actions-pool`) and
  **Provider** (`github-actions-provider`) configured to trust that
  specific OIDC issuer (`token.actions.githubusercontent.com`), and —
  critically — an **attribute condition** restricting it to tokens whose
  `repository` claim is exactly `makpevwei/datawise-ai`. No other GitHub
  repo, even one you create later, can use this pool without an explicit
  new binding.
- A dedicated service account, `github-actions-deployer@agentic-ai-488810.iam.gserviceaccount.com`,
  is the *only* identity the CI job ever becomes — scoped to the minimum
  roles the deploy actually needs (`run.admin`, `iam.serviceAccountUser`,
  `cloudbuild.builds.editor`, `artifactregistry.writer`, `storage.admin`
  for Cloud Build's staging bucket). Not project owner, not editor.
- At workflow run time, GitHub's OIDC token is exchanged for short-lived
  GCP credentials (minutes, not forever) scoped to that one service
  account. Nothing durable is stored anywhere.

Two non-secret identifiers (the provider's full resource name and the
service account's email) live in this repo's GitHub **Variables**
(`WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`, `GCP_PROJECT_ID`) —
safe to be visible, since knowing them alone grants no access without
also being a run of this specific repo.

## What's stored where

- **GitHub Secrets** (repo settings → Secrets and variables → Actions →
  Secrets): every env var the backend needs at runtime (`DATABASE_URL`,
  `JWT_SECRET_KEY`, `LLM_API_KEY`, `SMTP_PASSWORD`, ...) — encrypted,
  never shown again after being set, only injected into the deploy job's
  environment at run time.
- **GitHub Variables** (same page, Variables tab): the three WIF
  identifiers above — not secret, just configuration.
- **Google Cloud Storage** (`datawise-ai-storage-agentic` bucket, mounted
  into the Cloud Run container at `/data`): uploaded datasets and
  documents, so they survive a container restart (Cloud Run's local disk
  otherwise resets on every cold start).
- Nothing GCP-related is stored in this repo's code or in `.env` files
  committed to git.

## Branch protection on `main` — not currently enabled

**Status: blocked, not configured.** GitHub's branch protection feature is
gated behind the paid Pro plan for a private repository — Free-plan
private repos can't use it at all. Since this repo was deliberately made
private earlier (to keep the source code from being publicly visible),
the choice for now (see TODO.md) is to stay private and free rather than
either pay (~$4/month for GitHub Pro) or make the repo public. Revisit
this if/when either tradeoff changes.

**What it would do once enabled** (Settings → Branches → branch
protection rule for `main`):

- **Require a pull request before merging** — direct pushes to `main`
  would be rejected outright, for everyone, including repo admins.
- **Require status checks to pass before merging** — the `backend` and
  `frontend` CI jobs must both succeed on the PR's latest commit.
- **Do not allow bypassing the above settings** — no admin override.

That combination is what would make "CI failing stops a deploy" fully
true, rather than being a check nobody's forced to look at.

## Changing what gets deployed

The deploy step's flags (memory, CPU, volume mount, env var list) live in
`.github/workflows/ci.yml`'s `deploy` job. To add a new env var the
backend needs: add it as a GitHub Secret, then add
`;NEW_VAR=${{ secrets.NEW_VAR }}` to the `--update-env-vars` line in that
same job.
