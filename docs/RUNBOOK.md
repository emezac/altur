# Call Analyzer — Operations Runbook

> **Audience:** Engineers on-call or responding to production incidents.  
> **Scope:** Step-by-step procedures to diagnose and recover from specific failure conditions.  
> **Playbook:** For architecture and conceptual context see [`PLAYBOOK.md`](./PLAYBOOK.md).

---

## Quick Reference — Health & Status

```bash
# Health check
curl -s http://localhost:8000/health | jq .

# Expected healthy response
{ "status": "ok", "db": true, "queue": true }

# Specific call status
curl -s http://localhost:8000/api/v1/calls/<CALL_ID>/status | jq .
```

---

## Runbook Index

| # | Scenario | Section |
|---|----------|---------|
| RB-01 | Call stuck in PENDING | [§1](#rb-01-call-stuck-in-pending) |
| RB-02 | Call stuck in TRANSCRIBING or ANALYZING | [§2](#rb-02-call-stuck-in-transcribing-or-analyzing) |
| RB-03 | Call in FAILED state | [§3](#rb-03-call-in-failed-state) |
| RB-04 | `POST /calls` returns 503 | [§4](#rb-04-post-calls-returns-503) |
| RB-05 | `POST /calls` returns 413 | [§5](#rb-05-post-calls-returns-413) |
| RB-06 | `GET /health` returns DB: false | [§6](#rb-06-get-health-returns-db-false) |
| RB-07 | `GET /health` returns queue: false | [§7](#rb-07-get-health-returns-queue-false) |
| RB-08 | LLM returns `needs_review: true` | [§8](#rb-08-llm-returns-needs_review-true) |
| RB-09 | High OpenAI costs or quota exceeded | [§9](#rb-09-high-openai-costs-or-quota-exceeded) |
| RB-10 | Database migration fails | [§10](#rb-10-database-migration-fails) |
| RB-11 | Audio file not found in storage | [§11](#rb-11-audio-file-not-found-in-storage) |
| RB-12 | Roll back a bad deploy | [§12](#rb-12-roll-back-a-bad-deploy) |
| RB-13 | Complete data export for a call | [§13](#rb-13-complete-data-export-for-a-call) |
| RB-14 | Manually override a tag | [§14](#rb-14-manually-override-a-tag) |

> **First-time deploy / releases:** see [Deployment Procedure & Credentials Setup](#deployment-procedure--credentials-setup) (Heroku, AWS S3, GitHub credential setup).

---

## RB-01 — Call Stuck in PENDING

**Symptom:** A call was uploaded, received `202 Accepted`, but status remains `PENDING` indefinitely.

**Cause:** The background worker never processed the job — either the task was not enqueued or the worker is not running.

### Diagnosis

```bash
# 1. Check call status
curl -s http://localhost:8000/api/v1/calls/<CALL_ID>/status | jq .

# 2. Check health endpoint to verify queue is alive
curl -s http://localhost:8000/health | jq .

# 3. In production: check RQ worker is running
ps aux | grep rq

# 4. Inspect recent error events for the call
# (use the SQLite CLI in local dev)
sqlite3 dev.db \
  "SELECT * FROM call_events WHERE call_id='<CALL_ID>' ORDER BY created_at DESC LIMIT 10;"
```

### Resolution

```bash
# Option A: Retry the call via API (if the call is FAILED or if you manually set it)
curl -s -X POST http://localhost:8000/api/v1/calls/<CALL_ID>/retry | jq .

# Option B: Restart the worker (production)
# Heroku:
heroku ps:restart worker -a your-app

# Docker:
docker compose restart worker

# Option C: If queue is empty but worker is running, call was never enqueued.
# Force re-enqueue by retrying — first set status to FAILED in the DB:
sqlite3 dev.db \
  "UPDATE calls SET status='FAILED', updated_at=datetime('now') WHERE id='<CALL_ID>';"
curl -s -X POST http://localhost:8000/api/v1/calls/<CALL_ID>/retry | jq .
```

> [!WARNING]
> Directly editing the database is a last resort. Always prefer the `/retry` API endpoint when possible.

---

## RB-02 — Call Stuck in TRANSCRIBING or ANALYZING

**Symptom:** A call has been in `TRANSCRIBING` or `ANALYZING` for more than 5 minutes.

**Cause:** The worker process likely crashed mid-task, or the provider (OpenAI) returned a timeout.

### Diagnosis

```bash
# Check event log for errors
sqlite3 dev.db \
  "SELECT event_type, payload, created_at FROM call_events
   WHERE call_id='<CALL_ID>' ORDER BY created_at DESC LIMIT 20;"

# In production: check worker logs
heroku logs --tail --ps worker -a your-app
# or Docker:
docker compose logs -f worker
```

### Resolution

The state machine will **reject** any new task delivery if the status is not the expected starting state. To unstick:

```bash
# 1. Force status to FAILED so that retry routing works correctly
sqlite3 dev.db \
  "UPDATE calls SET status='FAILED', updated_at=datetime('now') WHERE id='<CALL_ID>';"

# 2. Retry via API — routing logic resumes from correct stage automatically
curl -s -X POST http://localhost:8000/api/v1/calls/<CALL_ID>/retry | jq .
```

**Retry routing logic:**
- `FAILED` with no transcript → re-enqueues `transcribe_call`
- `FAILED` with transcript → re-enqueues `analyze_call`

---

## RB-03 — Call in FAILED State

**Symptom:** A call shows `status: FAILED` in the API.

### Diagnosis

```bash
# 1. Get status + error message
curl -s http://localhost:8000/api/v1/calls/<CALL_ID>/status | jq .

# 2. Get full event log
curl -s http://localhost:8000/api/v1/calls/<CALL_ID> | jq '.events'

# 3. Get raw ERROR event payload
sqlite3 dev.db \
  "SELECT payload, created_at FROM call_events
   WHERE call_id='<CALL_ID>' AND event_type='ERROR' ORDER BY created_at DESC;"
```

### Common Root Causes

| Error in payload | Cause | Fix |
|-----------------|-------|-----|
| `OpenAI API error 401` | Invalid or missing `OPENAI_API_KEY` | Set correct key in `.env` and restart |
| `OpenAI API error 429` | Rate limit exceeded | Wait and retry, or switch `LLM_PROVIDER=fake` temporarily |
| `Transcript record not found` | DB write failed during `transcribe_call` | Retry — will re-run from transcription |
| `Connection refused` | Redis/Postgres unreachable | See RB-06 / RB-07 |
| `File not found at storage_path` | Audio file was deleted | Re-upload the audio file |

### Resolution

```bash
# Retry the call (resumes from last successful stage)
curl -s -X POST http://localhost:8000/api/v1/calls/<CALL_ID>/retry | jq .

# If retry count is high and errors repeat, investigate root cause before retrying again.
sqlite3 dev.db "SELECT retry_count FROM calls WHERE id='<CALL_ID>';"
```

---

## RB-04 — `POST /calls` Returns 503

**Symptom:** Upload endpoint returns `{"error": {"code": "QUEUE_UNAVAILABLE", ...}}`.

**Cause:** Redis is unreachable. The platform refuses to accept calls without a worker that can process them.

### Diagnosis

```bash
# 1. Health check
curl -s http://localhost:8000/health | jq .
# Expected: { "queue": false }

# 2. Test Redis connectivity directly
redis-cli -u "$REDIS_URL" ping
```

### Resolution

```bash
# Option A: Start Redis locally
redis-server &

# Option B: Heroku Redis add-on
heroku addons:info heroku-redis -a your-app
heroku redis:info -a your-app

# Option C: In local_dev mode (no Redis needed)
# Set REDIS_URL= (empty) in .env to revert to fakeredis burst mode
REDIS_URL=

# After Redis is back, the health check should return 200 automatically.
```

---

## RB-05 — `POST /calls` Returns 413

**Symptom:** Upload returns `413` or `VALIDATION_ERROR` with size message.

**Cause:** Audio file exceeds `MAX_UPLOAD_MB` (default: 100 MB).

### Resolution

```bash
# Check current limit
grep MAX_UPLOAD_MB .env

# Option A: Compress the audio before uploading
ffmpeg -i large_call.wav -b:a 128k compressed_call.mp3

# Option B: Raise the limit in .env (consider storage cost implications)
MAX_UPLOAD_MB=200
# Restart the server after changing .env
```

---

## RB-06 — `GET /health` Returns `db: false`

**Symptom:** Health check shows `{"db": false, "status": "unhealthy"}`.

### Diagnosis

```bash
# 1. Verify DATABASE_URL in .env
grep DATABASE_URL .env

# 2. Test connection directly
# SQLite:
sqlite3 dev.db ".tables"
# Postgres:
psql "$DATABASE_URL" -c "SELECT 1;"

# 3. Check if migrations have been applied
alembic current
```

### Resolution

```bash
# SQLite — file permission issue
ls -la dev.db
chmod 664 dev.db

# SQLite — corrupted (last resort)
sqlite3 dev.db ".recover" > recovered.sql
# Create new DB and import

# Postgres — connection refused
# Check host, port, user, and password in DATABASE_URL
# Verify Postgres service is running:
pg_isready -d "$DATABASE_URL"

# Migrations not applied
alembic upgrade head
```

---

## RB-07 — `GET /health` Returns `queue: false`

**Symptom:** Health check shows `{"queue": false}`.

See **RB-04** for Redis diagnosis and remediation steps. The health check and the upload 503 guard share the same `check_redis()` function.

---

## RB-08 — LLM Returns `needs_review: true`

**Symptom:** A call is `COMPLETED` but the summary shows `"needs_review": true` and/or `"executive_summary"` contains `"Review Required"`.

**Cause:** The LLM returned malformed JSON twice in a row. The self-repair loop exhausted and fell back to a safe placeholder payload.

### Diagnosis

```bash
# Get the raw summary insights blob
curl -s http://localhost:8000/api/v1/calls/<CALL_ID> | \
  jq '.summary.insights'

# Check event log for warnings logged during parsing
# (look for "self-repair" entries in application logs)
```

### Resolution

```bash
# Option A: Retry analysis (will re-run LLM with the stored transcript)
# First set status to TRANSCRIBED (before analyze_call) so retry picks correct stage:
sqlite3 dev.db \
  "UPDATE calls SET status='FAILED', updated_at=datetime('now') WHERE id='<CALL_ID>'; \
   DELETE FROM summaries WHERE call_id='<CALL_ID>'; \
   DELETE FROM call_tags WHERE call_id='<CALL_ID>' AND source='model';"

curl -s -X POST http://localhost:8000/api/v1/calls/<CALL_ID>/retry | jq .

# Option B: Manual override via API
curl -s -X PATCH http://localhost:8000/api/v1/calls/<CALL_ID>/tags \
  -H "Content-Type: application/json" \
  -d '{"category": "outcome", "value": "no_decision", "reason": "Manual review after needs_review flag"}'
```

> [!TIP]
> If this happens repeatedly, check the LLM model being used. `gpt-4o-mini` may be less reliable on very short or noisy transcripts. Consider switching to `OPENAI_LLM_MODEL=gpt-4o`.

---

## RB-09 — High OpenAI Costs or Quota Exceeded

**Symptom:** Unexpected API spend, or `429 Too Many Requests` errors.

### Immediate Mitigation

```bash
# Switch to fake providers immediately (zero cost, no restart required — edit .env and SIGHUP)
STT_PROVIDER=fake
LLM_PROVIDER=fake

# Restart server to apply
uvicorn app.main:app --port 8000
# or Heroku:
heroku ps:restart web -a your-app
```

### Investigation

```bash
# Count calls processed with openai providers in the last 24h
sqlite3 dev.db \
  "SELECT COUNT(*) FROM summaries
   WHERE llm_provider='openai'
   AND created_at >= datetime('now', '-1 day');"

# Check for runaway retries (high retry_count)
sqlite3 dev.db \
  "SELECT id, status, retry_count FROM calls
   WHERE retry_count > 3 ORDER BY retry_count DESC LIMIT 10;"
```

---

## RB-10 — Database Migration Fails

**Symptom:** `alembic upgrade head` exits with an error.

### Diagnosis

```bash
# Check current revision
alembic current

# See pending migrations
alembic history --indicate-current

# Run with verbose output
alembic upgrade head --sql  # dry-run: prints SQL without executing
```

### Resolution

```bash
# Option A: If a partial migration ran, roll back to last known good
alembic downgrade -1
# Fix the migration file, then:
alembic upgrade head

# Option B: Stamp current DB to skip a bad auto-generated migration
alembic stamp <revision_id>  # use ID from `alembic history`

# Option C: For development only — recreate DB from scratch
rm dev.db
alembic upgrade head
```

> [!CAUTION]
> Never use `alembic stamp` or `rm dev.db` in production without a verified backup.

---

## RB-11 — Audio File Not Found in Storage

**Symptom:** `GET /calls/{id}/audio` returns `404 "Audio file not found in storage"`.

### Diagnosis

```bash
# Find storage_path
sqlite3 dev.db "SELECT storage_path FROM calls WHERE id='<CALL_ID>';"

# Check if file exists (local storage)
ls -la <storage_path>

# Check if S3 object exists (S3 backend)
aws s3 ls s3://$S3_BUCKET_NAME/<storage_path>
```

### Resolution

```bash
# If the file was accidentally deleted, there is no automated recovery.
# Options:
# 1. Re-upload the original audio file via POST /calls
# 2. If analysis results are intact, the transcript and summary are preserved in the DB.
#    Export the data:
curl -s http://localhost:8000/api/v1/calls/<CALL_ID>/export > call_export.json

# Mark the call as needing re-upload via a tag override:
curl -s -X PATCH http://localhost:8000/api/v1/calls/<CALL_ID>/tags \
  -H "Content-Type: application/json" \
  -d '{"category": "compliance_flag", "value": "pii_shared", "reason": "Audio file missing — re-upload required"}'
```

---

## RB-12 — Roll Back a Bad Deploy

**Symptom:** A new version introduces a regression. Need to revert.

### Git-Based Rollback

```bash
# Find last known good commit
git log --oneline -10

# Revert to specific commit
git checkout <good-commit-sha> -- .
git commit -m "chore: rollback to <good-commit-sha>"
git push

# Heroku
heroku releases -a your-app
heroku rollback v<N> -a your-app  # replace N with previous release number
```

### Database Rollback (if migration was included)

```bash
# Step back one migration
alembic downgrade -1

# Then deploy the previous code version
```

> [!CAUTION]
> Downgrading a migration in production requires a maintenance window and a verified backup.

---

## RB-13 — Complete Data Export for a Call

**Symptom / Task:** Need to extract all data for a call (transcript, summary, tags, events) for audit or external reporting.

```bash
# Via API (recommended — includes effective tags and override history)
curl -s http://localhost:8000/api/v1/calls/<CALL_ID>/export \
  -o call_<CALL_ID>_export.json

# Via SQLite (raw data)
sqlite3 -json dev.db "
  SELECT
    c.id, c.filename, c.status, c.uploaded_at,
    t.raw_text, t.turns,
    s.summary_text, s.key_points, s.insights,
    json_group_array(json_object('cat', ct.tag_category, 'val', ct.tag_value, 'src', ct.source)) AS tags
  FROM calls c
  LEFT JOIN transcripts t ON t.call_id = c.id
  LEFT JOIN summaries s ON s.call_id = c.id
  LEFT JOIN call_tags ct ON ct.call_id = c.id
  WHERE c.id = '<CALL_ID>'
  GROUP BY c.id;
" | jq . > call_<CALL_ID>_raw.json
```

---

## RB-14 — Manually Override a Tag

**Symptom / Task:** The model assigned an incorrect tag and you need to correct it without re-running the pipeline.

```bash
# Supported categories: outcome, next_step, objection, compliance_flag, product_interest
curl -s -X PATCH http://localhost:8000/api/v1/calls/<CALL_ID>/tags \
  -H "Content-Type: application/json" \
  -d '{
    "category": "outcome",
    "value": "converted",
    "reason": "Sales rep confirmed deal closed via CRM on 2026-07-13"
  }'

# HTTP 204 No Content = success
# Verify override was applied:
curl -s http://localhost:8000/api/v1/calls/<CALL_ID> | jq '.tags'
```

The override creates an immutable audit event (`TAG_OVERRIDE`) with the reason. The effective tag is immediately updated in analytics and exports.

---

## Useful One-Liners

```bash
# List all FAILED calls
sqlite3 dev.db "SELECT id, filename, retry_count FROM calls WHERE status='FAILED' ORDER BY updated_at DESC;"

# List all calls with needs_review=true
sqlite3 -json dev.db "
  SELECT c.id, c.filename, c.uploaded_at
  FROM calls c JOIN summaries s ON s.call_id = c.id
  WHERE json_extract(s.insights, '$.needs_review') = 1;" | jq .

# Top 5 most common objections (excluding no_objections_raised)
sqlite3 dev.db "
  SELECT tag_value, COUNT(*) n FROM call_tags
  WHERE tag_category='objection' AND tag_value != 'no_objections_raised'
  GROUP BY tag_value ORDER BY n DESC LIMIT 5;"

# Retry ALL failed calls
sqlite3 dev.db "SELECT id FROM calls WHERE status='FAILED';" | while read id; do
  echo "Retrying $id..."
  curl -s -X POST http://localhost:8000/api/v1/calls/$id/retry > /dev/null
done

# Check migration status
cd altur/backend && source .venv/bin/activate && alembic current

# Tail application logs (local uvicorn)
uvicorn app.main:app --port 8000 --log-level info 2>&1 | grep -v "^INFO:.*GET /health"
```

---

# Deployment Procedure & Credentials Setup

> **Audience:** Whoever performs the first production provisioning or a routine release.
> **Key principle:** the DEV→PROD switch is **100% environment-variable driven** — there is no code change between environments. Deploying is about setting the right config values, not editing the app. In `LOCAL_DEV` every default resolves to a zero-dependency stack (fake providers, SQLite, inline `fakeredis`, local disk), which is why local runs never hit a credential/config problem; `CLOUD` is the first environment that talks to real external services, so this section is where credentials actually matter.

## DP.0 — Environment model (config, not code)

| Variable | `LOCAL_DEV` default | `CLOUD` (Heroku) value |
|----------|---------------------|------------------------|
| `APP_ENV` | `local_dev` | `cloud` |
| `DATABASE_URL` | `sqlite:///./dev.db` | Postgres URL (set by the Heroku Postgres addon) |
| `REDIS_URL` | *(empty → `fakeredis`, inline)* | `rediss://…` (set by the Heroku Redis addon) |
| `STORAGE_BACKEND` | `local` | `s3` |
| `STT_PROVIDER` / `LLM_PROVIDER` | `fake` | `openai` (or another real provider) |
| `CORS_ORIGINS` | `http://localhost:5173` | your real app domain (never `*` in prod) |
| `SECRET_KEY` | `change-me` | a fresh 64-hex random value |

The DB layer already adapts (`sqlite` connect-args vs. Postgres pooling), the queue layer handles `rediss://` TLS, migrations are Postgres-safe (`JSON().with_variant(JSONB, "postgresql")`), and storage/provider selection is by factory — so **no code path is environment-specific beyond reading these variables.**

## DP.1 — Accounts & tools required

- **GitHub** account + this repo pushed (source of truth for deploys).
- **Heroku** account + [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli) (`heroku login`).
- **AWS** account (for the S3 audio bucket) + optionally the AWS CLI.
- **OpenAI** API key (or the chosen real STT/LLM provider).

## DP.2 — Credentials matrix

| Credential | Purpose | Where to obtain | Where it lives (never in git) |
|------------|---------|-----------------|-------------------------------|
| `OPENAI_API_KEY` | Real STT/LLM | platform.openai.com → API keys | Heroku config var |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | S3 upload/playback | AWS IAM user access key (DP.3) | Heroku config var |
| `S3_BUCKET_NAME` / `S3_REGION` | Target bucket | AWS S3 (DP.3) | Heroku config var |
| `SECRET_KEY` | App signing | `python -c "import secrets;print(secrets.token_hex(32))"` | Heroku config var |
| `HEROKU_API_KEY` | CI deploys (optional) | `heroku authorizations:create` | GitHub Actions secret |
| Heroku `DATABASE_URL` / `REDIS_URL` | Managed DB/queue | Auto-set by addons | Heroku (managed) |

> **Golden rule:** secrets live in the platform's secret store (Heroku config vars, GitHub Actions secrets), **never** in the repo. `.env` is git-ignored and confirmed untracked; keep it that way.

## DP.3 — AWS S3 setup

1. **Create a private bucket** (block all public access) in your region, e.g. `call-analyzer-audio-prod` in `us-east-1`.
2. **Create a least-privilege IAM user** (programmatic access only) with a policy scoped to *just this bucket*:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject", "s3:ListBucket"],
       "Resource": [
         "arn:aws:s3:::call-analyzer-audio-prod",
         "arn:aws:s3:::call-analyzer-audio-prod/*"
       ]
     }]
   }
   ```
3. **Generate an access key** for that user → this yields `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.
4. **(Recommended) Lifecycle rule:** expire raw audio objects after 7–30 days (PII minimization — see `architecture_scale.md` §6). The de-identified transcript remains in Postgres.
5. The bucket stays **private**: playback works via short-lived **presigned GET URLs** (the API 307-redirects to them), so no public ACLs or bucket CORS are needed.

## DP.4 — GitHub setup

1. Push the repo (`altur/` is the repo root). Confirm the secret file is ignored:
   ```bash
   git check-ignore .env        # must print ".env"
   git ls-files | grep -E "(^|/)\.env$"   # must print nothing
   ```
2. **Deploy option A (manual):** deploy straight from your machine with the Heroku git remote (DP.5). Simplest; recommended for the take-home.
3. **Deploy option B (CI/CD):** GitHub Actions on push to `main`. Store `HEROKU_API_KEY` and `HEROKU_APP_NAME` as **GitHub → Settings → Secrets and variables → Actions**, then use a deploy step:
   ```yaml
   # .github/workflows/deploy.yml (optional)
   - uses: akhileshns/heroku-deploy@v3.13.15
     with:
       heroku_api_key: ${{ secrets.HEROKU_API_KEY }}
       heroku_app_name: ${{ secrets.HEROKU_APP_NAME }}
       heroku_email: ${{ secrets.HEROKU_EMAIL }}
   ```
   Never echo secrets in workflow logs.

## DP.5 — Heroku setup & first deploy

```bash
# 1. Authenticate and create the app
heroku login
heroku create call-analyzer-altur

# 2. Python buildpack only (frontend is static, served by FastAPI — no Node build)
heroku buildpacks:add heroku/python

# 3. Managed Postgres + Redis (these auto-set DATABASE_URL and REDIS_URL)
heroku addons:create heroku-postgresql:essential-0
heroku addons:create heroku-redis:mini

# 4. Set config vars (the DEV→PROD switch). Replace placeholders with real values.
heroku config:set \
  APP_ENV=cloud \
  STORAGE_BACKEND=s3 \
  STT_PROVIDER=openai LLM_PROVIDER=openai \
  OPENAI_API_KEY=sk-... \
  S3_BUCKET_NAME=call-analyzer-audio-prod S3_REGION=us-east-1 \
  AWS_ACCESS_KEY_ID=AKIA... AWS_SECRET_ACCESS_KEY=... \
  CORS_ORIGINS=https://call-analyzer-altur.herokuapp.com \
  SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))")

# 5. Deploy. The `release` process runs `alembic upgrade head` automatically.
git push heroku main

# 6. Scale one web dyno and one worker dyno
heroku ps:scale web=1 worker=1
```

> **Note (`S3_ENDPOINT_URL`):** leave it **unset** for real AWS. It is only for the local MinIO in docker-compose (`http://minio:9000`).

## DP.6 — Post-deploy verification

```bash
heroku open                                            # loads the SPA
curl -s https://<app>.herokuapp.com/health             # {"status":"ok","db":true,"queue":true}
curl -s https://<app>.herokuapp.com/api/v1/calls       # paginated list responds
heroku logs --tail                                     # watch the release migration + first requests
```
Then upload an audio through the UI and confirm it reaches `COMPLETED` and the audio player streams from the presigned URL.

## DP.7 — Security checklist

- [ ] `.env` git-ignored and untracked (verified in DP.4).
- [ ] AWS IAM key scoped to the single bucket (DP.3), not an admin key.
- [ ] `CORS_ORIGINS` set to the real domain, **not** `*`.
- [ ] `SECRET_KEY` is a fresh random value, not `change-me`.
- [ ] S3 bucket blocks all public access; raw-audio lifecycle expiry enabled.
- [ ] Rotate `OPENAI_API_KEY` / AWS keys periodically; rotation = `heroku config:set` (triggers a restart).

## DP.8 — Routine releases & rollback

```bash
git push heroku main         # release phase re-runs migrations automatically
```
To roll back a bad deploy, see **[RB-12 — Roll back a bad deploy](#rb-12-roll-back-a-bad-deploy)**.
