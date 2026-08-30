# Deploy Pipeline

How a code change actually reaches production, end to end.

## The flow

1. Work happens on a branch, not directly on `main` (branch protection
   enforces this — see below).
2. Open a PR into `main`. GitHub Actions' `backend` and `frontend` jobs
   (`.github/workflows/ci.yml`) run automatically: lint, a real `next build`,
   type-checking, and the test suites (backend against a real ephemeral
   Postgres service container).
3. Branch protection requires both jobs to pass before the PR's merge
   button unlocks. A red CI blocks the merge — there is no bypass, not
   even for repo admins.
4. Once merged, `main` gets the push. Two things happen automatically,
   with no manual command:
   - **Vercel** deploys the frontend from its own GitHub integration
     (unrelated to this repo's CI setup — Vercel watches pushes to `main`
     directly). Since nothing broken can reach `main` per step 3, this is
     never a broken build.
   - **GitHub Actions' `deploy` job** runs, but only after `backend` and
     `frontend` succeed again on `main` itself (`needs: [backend,
     frontend]`) and only on an actual push to `main` — not on PRs, so a
     PR from a fork can never trigger a deploy. It authenticates to
     Google Cloud via Workload Identity Federation and runs `gcloud run
     deploy` against Cloud Run.

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

## Branch protection on `main`

Configured via GitHub repo settings (Settings → Branches → branch
protection rule for `main`):

- **Require a pull request before merging** — direct pushes to `main` are
  rejected outright, for everyone, including repo admins.
- **Require status checks to pass before merging** — the `backend` and
  `frontend` CI jobs must both succeed on the PR's latest commit.
- **Do not allow bypassing the above settings** — no admin override.

This is what makes "CI failing stops a deploy" actually true, rather than
being a check nobody's forced to look at.

## Changing what gets deployed

The deploy step's flags (memory, CPU, volume mount, env var list) live in
`.github/workflows/ci.yml`'s `deploy` job. To add a new env var the
backend needs: add it as a GitHub Secret, then add
`;NEW_VAR=${{ secrets.NEW_VAR }}` to the `--update-env-vars` line in that
same job.
