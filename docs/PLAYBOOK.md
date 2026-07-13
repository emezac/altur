# Call Analyzer — Operations Playbook

> **Audience:** Engineers who build, configure, or maintain the platform.  
> **Scope:** Architecture, pipeline lifecycle, provider setup, environments, and common workflows.  
> **Runbook:** For step-by-step incident procedures see [`RUNBOOK.md`](./RUNBOOK.md).

---

## 1. Platform Overview

Call Analyzer is a decoupled, asynchronous platform that ingests sales-call audio, transcribes it via a speech-to-text (STT) provider, and performs structured semantic analysis via a large-language-model (LLM) provider. Results are surfaced through a REST API and a single-page dashboard.

```
 Browser / API Client
        │
        ▼
 ┌─────────────┐    POST /api/v1/calls
 │  FastAPI    │──────────────────────────► SQLite / Postgres  (calls table)
 │  (ASGI)    │                                    │
 └─────┬───────┘                                   │
       │                                           ▼
       │  queue.enqueue(transcribe_call)    ┌──────────────┐
       ▼                                   │  Local disk  │
 ┌──────────────┐                          │  or S3 bucket│
 │  RQ Worker   │                          └──────────────┘
 │  (rq / fakeredis)                               ▲
 └──────┬───────┘                                  │ storage_path
        │                                          │
        ▼                                          │
 transcribe_call ─► STT Provider  ────────────────►│
        │            (fake | openai whisper-1)
        ▼
 analyze_call ───► LLM Provider ──► Summary + CallTag rows
                    (fake | gpt-4o-mini)
```

### Core Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| **FastAPI ASGI** | `app/main.py` | Request validation, routing, SPA serving |
| **Worker Tasks** | `app/workers/tasks.py` | `transcribe_call`, `analyze_call` |
| **State Machine** | `app/services/state_machine.py` | Atomic, idempotent status transitions |
| **STT Factory** | `app/services/stt/factory.py` | Selects `fake` or `openai` provider |
| **LLM Factory** | `app/services/llm/factory.py` | Selects `fake` or `openai` provider |
| **Storage Factory** | `app/services/storage/factory.py` | Selects `local` or `s3` backend |
| **Analytics Service** | `app/services/analytics_service.py` | Aggregates conversion, objections, volume |
| **Health Endpoint** | `app/api/health.py` | `GET /health` — DB + queue liveness |
| **Config** | `app/core/config.py` | Pydantic-settings; reads `.env` |

---

## 2. Call Lifecycle — State Machine

```
                       ┌─────────────────────────────────┐
                       │           PENDING                │  ◄── POST /calls
                       └────────────┬────────────────────┘
                                    │ transcribe_call()
                                    ▼
                       ┌─────────────────────────────────┐
                       │         TRANSCRIBING             │
                       └────────────┬────────────────────┘
                                    │ STT success
                                    ▼
                       ┌─────────────────────────────────┐
                       │          TRANSCRIBED             │
                       └────────────┬────────────────────┘
                                    │ analyze_call()
                                    ▼
                       ┌─────────────────────────────────┐
                       │           ANALYZING              │
                       └────────────┬────────────────────┘
                                    │ LLM + DB writes success
                                    ▼
                       ┌─────────────────────────────────┐
                       │           COMPLETED              │
                       └─────────────────────────────────┘

   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
   Any stage can transition to FAILED on unhandled errors.
   FAILED calls can be retried via POST /calls/{id}/retry.
```

Every transition is an **atomic conditional UPDATE**:

```sql
UPDATE calls SET status = :to, updated_at = now()
WHERE  id = :call_id AND status = :from;
-- Returns 0 rows → duplicate job delivery → task exits immediately (no double cost).
-- Returns 1 row → transition claimed → continue.
```

### Status → Progress Map

| Status | UI Progress % |
|--------|--------------|
| PENDING | 0 |
| TRANSCRIBING | 25 |
| TRANSCRIBED | 50 |
| ANALYZING | 75 |
| COMPLETED | 100 |
| FAILED | — |

---

## 3. Environment Modes

### 3.1 `local_dev` (Default)

Uses **fakeredis** (in-memory) as the queue in burst mode. Tasks execute synchronously in the same thread, immediately after `queue.enqueue()` returns. No Redis process required.

```
APP_ENV=local_dev
REDIS_URL=              # empty → fakeredis / synchronous burst mode
DATABASE_URL=sqlite:///./dev.db
STT_PROVIDER=fake
LLM_PROVIDER=fake
STORAGE_BACKEND=local
```

### 3.2 `staging` / `production` (Heroku / Docker)

Redis and Postgres are provisioned as services. Workers run as a separate dyno/container.

```
APP_ENV=production
REDIS_URL=redis://:password@host:6379/0
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/call_analyzer
STT_PROVIDER=openai
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
STORAGE_BACKEND=s3
S3_BUCKET_NAME=call-analyzer-audio
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
S3_REGION=us-east-1
```

---

## 4. Provider Configuration

### STT Providers

| `STT_PROVIDER` | Class | Notes |
|---------------|-------|-------|
| `fake` | `FakeSTTProvider` | Returns fixture JSON; keyed by filename. Zero cost, fully offline. |
| `openai` | `OpenAIWhisperProvider` | Requires `OPENAI_API_KEY`; calls `whisper-1` (default). |

### LLM Providers

| `LLM_PROVIDER` | Class | Notes |
|---------------|-------|-------|
| `fake` | `FakeLLMProvider` | Returns fixture JSON; keyed by filename/keyword. Zero cost, fully offline. |
| `openai` | `OpenAILLMProvider` | Requires `OPENAI_API_KEY`; calls `gpt-4o-mini` (default). |

> **Changing the LLM model:** Set `OPENAI_LLM_MODEL=gpt-4o` for higher quality, or `OPENAI_LLM_MODEL=gpt-4o-mini` for lower cost.

### Storage Backends

| `STORAGE_BACKEND` | Class | Notes |
|------------------|-------|-------|
| `local` | `LocalDiskStorage` | Writes to `LOCAL_STORAGE_PATH`. Default: `./data/audio`. |
| `s3` | `S3Storage` | Requires `S3_BUCKET_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`. Set `S3_ENDPOINT_URL` for MinIO. |

---

## 5. LLM Parsing — Self-Repair Loop

The `analyze_call` task implements a two-stage error boundary for LLM JSON parsing:

```
llm.complete_json(prompt, transcript)
       │
       ▼
  json.loads() + schema check
       │
   ┌───┴─────────────────────┐
   │ OK                      │ JSONDecodeError / missing keys
   ▼                         ▼
 Persist to DB         Self-repair prompt (1 retry)
                              │
                       ┌──────┴──────────────────────┐
                       │ OK                          │ Fails again
                       ▼                             ▼
                  Persist to DB             needs_review = True
                                            Fallback payload persisted
                                            status → COMPLETED (not FAILED)
```

- **Infrastructure errors** (provider raises, network timeout) → caller exception → FAILED state.
- **Parsing errors** → self-repair → fallback → COMPLETED with `needs_review: true` flag.

---

## 6. Audit Trail — `call_events` Table

Every meaningful state change and error creates an immutable row:

| `event_type` | Triggered by |
|-------------|-------------|
| `STATUS_CHANGE` | Every `state_machine.transition()` success |
| `ERROR` | Unhandled exception in any worker task |
| `TAG_OVERRIDE` | `PATCH /calls/{id}/tags` |

Query recent errors:
```sql
SELECT call_id, created_at, payload
FROM   call_events
WHERE  event_type = 'ERROR'
ORDER  BY created_at DESC
LIMIT  20;
```

---

## 7. Tag Schema

Tags are stored as EAV rows in `call_tags`. Two sources exist:

| Source | Priority | API |
|--------|----------|-----|
| `model` | Lower | Written by `analyze_call` |
| `override` | **Higher** | Written by `PATCH /calls/{id}/tags` |

The analytics service and export endpoint always resolve **effective tags** (override beats model for the same category).

### Allowed Categories & Values

| Category | Closed Values | Open List? |
|----------|-------------|-----------|
| `outcome` | `converted`, `sale_made`, `deal_closed`, `won_deal_closed`, `no_decision`, `rejected`, `lost_deal` | No |
| `next_step` | `schedule_demo`, `send_proposal`, `call_again_follow_up`, `no_follow_up` | No |
| `objection` | `price_budget`, `timing`, `competitor`, `authority_decision_maker`, `need_fit`, `no_objections_raised` | No |
| `compliance_flag` | `none`, `pii_shared`, `promise_made`, `regulatory_violation` | No |
| `product_interest` | Any string | **Yes** |

---

## 8. Analytics Endpoint

`GET /api/v1/analytics/summary`

Returns aggregated metrics over all COMPLETED calls (supports `date_from` / `date_to` filters):

| Field | Description |
|-------|-------------|
| `total_calls` | Total ingested |
| `by_status` | Count per status bucket |
| `conversion_rate` | % of calls with outcome in `{converted, sale_made, deal_closed, won_deal_closed}` |
| `converted_calls` | Raw conversion count |
| `sentiment_distribution` | Count per sentiment value |
| `top_objection` | Most frequent objection (excludes `no_objections_raised`) |
| `avg_duration_seconds` | Average audio length |
| `volume_by_day` | `[{date, count}]` array sorted ascending |

---

## 9. API Reference

Base path: `/api/v1`

### Ingestion

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/calls` | Upload audio file. 202 on success, 400 validation, 413 too large, 503 queue down |

### Retrieval

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/calls` | Paginated list. Params: `page`, `page_size`, `status`, `tag`, `date_from`, `date_to`, `q` |
| `GET` | `/calls/{id}` | Full detail: transcript, summary, tags, events |
| `GET` | `/calls/{id}/status` | Lightweight status + progress % for polling |
| `GET` | `/calls/{id}/audio` | Stream raw audio file |
| `GET` | `/calls/{id}/export` | Export call as self-contained JSON attachment |

### Operations

| Method | Path | Description |
|--------|------|-------------|
| `PATCH` | `/calls/{id}/tags` | Override tag values (creates audit event) |
| `POST` | `/calls/{id}/retry` | Re-enqueue FAILED call from correct stage |

### Analytics

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/analytics/summary` | Aggregated platform metrics |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | DB + queue liveness. 200 healthy, 503 unhealthy |

---

## 10. Database Schema (Summary)

```
calls
  id (UUID PK)  filename  status  storage_path
  mime_type  file_size_bytes  duration_seconds
  uploaded_at  updated_at  retry_count

transcripts
  id (PK)  call_id (FK)  raw_text  turns (JSON)
  language  stt_provider  stt_model  stt_confidence

summaries
  id (PK)  call_id (FK)  summary_text  key_points (JSON)
  insights (JSON)  llm_provider  llm_model  prompt_version

call_tags
  id (PK)  call_id (FK)  tag_category  tag_value
  confidence  source (model | override)  created_at

call_tag_overrides
  id (PK)  call_id (FK)  category  value  reason  created_at

call_events
  id (PK)  call_id (FK)  event_type  payload (JSON)  created_at
```

---

## 11. Development Workflows

### Set Up Development Environment

```bash
cd altur/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp ../.env.example ../.env          # edit OPENAI_API_KEY if needed
alembic upgrade head
uvicorn app.main:app --port 8000 --reload
```

### Run All Offline Tests

```bash
PYTHONPATH=. pytest -m "not slow" --tb=short
```

### Run With Coverage

```bash
PYTHONPATH=. pytest -m "not slow" --cov=app --cov-report=term-missing
```

### Run Contract Tests (Real OpenAI)

```bash
OPENAI_API_KEY=sk-... PYTHONPATH=. pytest -m slow --tb=short
```

### Apply Database Migrations

```bash
alembic upgrade head           # forward
alembic downgrade -1           # one step back
alembic current                # current revision
alembic history                # full migration history
```

### Generate New Migration

```bash
alembic revision --autogenerate -m "add_new_column"
# Review generated file in alembic/versions/ before committing.
```

### Switch to Real Providers

Edit `.env`:
```
STT_PROVIDER=openai
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

No code changes required — factories read from `settings` at import time.

---

## 12. Feature Flags

| Flag | Default | Effect |
|------|---------|--------|
| `ENABLE_VAD_CHUNKING` | `false` | Voice-activity-detection chunking before STT (not yet implemented) |
| `ENABLE_PII_REDACTION` | `false` | PII scrubbing before LLM (not yet implemented) |
| `MAX_UPLOAD_MB` | `100` | Maximum allowed audio file size |
| `FAKE_PROCESSING_DELAY_SECONDS` | `2.0` | Artificial latency in fake providers (useful for testing UI polling) |
