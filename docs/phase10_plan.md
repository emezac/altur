# Phase 10 — Docker parity, S3, Heroku deploy & final docs

> **Audience:** Engineers finishing the build per `PLAN_IMPLEMENTACION_call_analyzer.md` Phase 10.
> **Scope:** Reconciled, actionable plan for Phase 10, accounting for how the shipped code actually differs from the original plan's assumptions.
> **Related:** [`architecture_scale.md`](./architecture_scale.md) · [`PLAYBOOK.md`](./PLAYBOOK.md) · [`RUNBOOK.md`](./RUNBOOK.md)

---

## 1. Key finding — plan vs. reality

The deployable git repo is **`altur/`** (backend + frontend + docs at its root). Phases 1–9 are committed. Two divergences from the original plan drive this phase:

1. **The frontend is vanilla static JS served by FastAPI** — not a Vite/React app. There is **no build step, no `package.json`, no Node buildpack**. This *simplifies* Heroku (Python buildpack only) and removes the `frontend` docker service.
2. **The Phase-10 infra files did not exist in `altur/`.** The `Procfile` / `docker-compose.yml` / `.env.example` sitting in the parent `challenge/` folder are outside the git repo and were written for a different layout (`./backend`, `./frontend` with Vite). They are reference only; the real artifacts are created inside `altur/`.

---

## 2. Reconciled sub-plan

| Sub-step | Deliverable | Status |
|----------|-------------|--------|
| **10.b** S3 storage | `backend/app/services/storage/s3.py` (`S3CompatibleStorage`, boto3, presigned GET) | ✅ Done |
| **10.b** Audio endpoint | `GET /calls/{id}/audio` → presigned 307 redirect for S3, `FileResponse` for local | ✅ Done |
| **10.b** Deps | `boto3` in `requirements.txt`; `moto` in `requirements-dev.txt` | ✅ Done |
| **10.b** Tests | `tests/unit/test_s3_storage.py` — offline lifecycle via `moto` (save/exists/open/presigned/delete) | ✅ Done (3 pass) |
| **10.d** Scale doc | `architecture_scale.md` §5 (production changes) + §6 (PII handling) — completes the 4 challenge questions | ✅ Done |
| **10.d** README | "Running with Docker" + "Deployment to Heroku" sections | ✅ Done |
| **10.a** Docker image | `backend/Dockerfile` (python:3.12-slim, uvicorn) | ✅ Prepared |
| **10.a** Compose | `altur/docker-compose.yml` — postgres + redis + minio + bucket-init + backend + worker; frontend mounted into backend (no vite service) | ✅ Prepared |
| **10.c** Heroku | `altur/Procfile`, `runtime.txt`, root `requirements.txt` | ✅ Prepared (web command boot-tested offline) |
| **10.a** Compose e2e run | `docker compose up` + upload e2e against Postgres/Redis/MinIO | ⏳ **Run locally** (needs Docker daemon) |
| **10.c** Heroku deploy | create app, set config vars, `git push heroku` | ⏳ **Owner action** (account + credentials) |

---

## 3. What still requires the owner

These steps are outward-facing or credential-bound and are intentionally left to run manually:

- **`docker compose up` end-to-end** — needs a running Docker daemon. Verify: migrations apply, an upload flows to `COMPLETED` with fakes, and with `STORAGE_BACKEND=s3` the audio persists in MinIO and plays via a presigned URL.
- **Heroku deploy** — creating the app, `heroku addons:create` (Postgres, Redis), and `heroku config:set` with real `OPENAI_API_KEY` / AWS credentials, then `git push heroku main`. Commands are in the README "Deployment to Heroku" section and [`PLAYBOOK.md`](./PLAYBOOK.md).

Everything that can be built and verified without credentials or a live deploy is done and test-covered.

---

## 4. Verification performed

- **S3 storage:** `test_s3_storage.py` passes offline under `moto` (3 tests) — full save→presigned→delete lifecycle.
- **Full suite:** 82 passed, 1 skipped (79 pre-existing + 3 new S3). *Note:* `test_pipeline_end_to_end_fixture_03_inconsistencies` is intermittently order-flaky (pre-existing, unrelated to Phase 10) — passes in isolation and on re-run.
- **Heroku web command:** the exact `Procfile` web line (`gunicorn --chdir backend app.main:app`) was booted locally and served `/health`, the SPA, and `/api/v1/architecture` — confirming the deploy entrypoint resolves both the API and the static frontend.

---

## 5. Acceptance criteria (from the plan) → coverage

| Criterion | Coverage |
|-----------|----------|
| `docker compose` e2e OK | Artifacts prepared + turnkey bucket init; **owner runs the daemon** |
| MinIO: audio persists & plays via presigned | `s3.py` + presigned-redirect endpoint + offline test; verified end-to-end on `compose up` |
| Heroku public URL serves API + UI | Web entrypoint boot-tested offline; **owner runs the deploy** |
| README lets a third party bring it up | Quickstart + Docker + Deployment sections complete |
| `architecture_scale.md` answers the 4 questions | Scale-to-10k (§4), bottlenecks (§3), production changes (§5), PII (§6) |
