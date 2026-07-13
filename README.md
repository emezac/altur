# Call Analyzer — AI Sales Intelligence Suite

An automated, decoupled platform for sales call ingestion, speech-to-text (STT) transcription, and AI-powered semantic analysis. The system extracts summaries, key points, customer sentiments, purchase intent, and structured sales tagging classifications (outcomes, next steps, objections, and compliance flags) through an interactive SPA dashboard.

---

## 1. System Architecture

The application is built around a status-driven, decoupled background worker pipeline:

* **FastAPI Server:** Ingests audio files via REST API (`POST /api/v1/calls`), performs validation, persists metadata to SQLite, saves files to local storage, and enqueues background tasks.
* **Worker Queue (RQ):** Orchestrates tasks. Operates in `LOCAL_DEV` mode using synchronous inline execution with `fakeredis` (meaning task chains execute synchronously in the thread on request execution for simplified development and testing).
* **Orchestration Task Pipeline:**
  1. `transcribe_call`: Sets state to `TRANSCRIBING`, runs Whisper STT, saves raw transcript and turns to the `Transcript` table, updates state to `TRANSCRIBED`, and schedules analysis.
  2. `analyze_call`: Sets state to `ANALYZING`, runs sales insights LLM analysis, saves summaries to `Summary`, saves classification elements as EAV rows to `CallTag`, and updates state to `COMPLETED`.
  3. `Error Boundary Recovery`: Catches exceptions, updates the state to `FAILED`, and logs `ERROR` entries to the `CallEvent` audit trail.

---

## 2. Quickstart

### Prerequisites
* Python 3.10+
* sqlite3

### Setup & Run
1. **Clone and navigate to the project directory:**
   ```bash
   cd challenge
   ```

2. **Initialize Python environment & dependencies:**
   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

3. **Configure Environment Variables:**
   Create a `.env` file in `backend/`:
   ```env
   DATABASE_URL=sqlite:///dev.db
   LOCAL_STORAGE_PATH=data/audio
   REDIS_URL=
   CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000

   # LLM/STT providers — swappable via factory (see below)
   STT_PROVIDER=fake            # fake | openai
   LLM_PROVIDER=fake            # fake | openai | qwen
   ```

   **Pluggable LLM providers.** The analysis LLM is selected at runtime by
   `LLM_PROVIDER` through `app/services/llm/factory.py`:

   * `fake` — deterministic fixtures, no network/keys (default for tests).
   * `openai` — **production default**. Set `OPENAI_API_KEY` and optionally `OPENAI_LLM_MODEL` (default `gpt-4o-mini`).
   * `qwen` — **development**. Alibaba Qwen via the DashScope OpenAI-compatible
     endpoint. Set:
     ```env
     LLM_PROVIDER=qwen
     QWEN_TOKEN=sk-...
     QWEN_MODEL=qwen3.7-plus
     QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
     QWEN_ENABLE_THINKING=false   # true = deep-thinking (streams reasoning_content)
     ```
     Qwen's `-plus`/`-max` tiers are deep-thinking models: the provider always
     streams and keeps only the visible `content` (discarding `reasoning_content`),
     then strips any ```` ```json ```` fences before returning the JSON.

   Adding another provider is a single class implementing `LLMProvider.complete_json`
   plus one branch in the factory — no changes to the worker pipeline.

4. **Execute Database Migrations:**
   ```bash
   alembic upgrade head
   ```

5. **Start the Dev Server:**
   ```bash
   uvicorn app.main:app --port 8000
   ```

6. **Access the Web Application:**
   Open [http://localhost:8000/](http://localhost:8000/) in your web browser.

---

## 3. Web SPA Interface

The frontend is a lightweight, responsive dashboard with a modern dark theme and glassmorphic panels:
* **Audio Uploading:** Supports drag-and-drop file ingestion with live progress loaders.
* **Calls Listing:** Searchable sidebar containing current processing status badges (PENDING, TRANSCRIBING, COMPLETED, FAILED).
* **Interactive Player & Transcript:** Syncs transcription dialogues to audio playtime. Clicking any speech bubble/turn instantly seeks the audio player to that exact starting second and plays.
* **Insights Dashboard:** Displays summaries, sentiment metrics, intent levels, checklists, objections, and timeline logs.

---

## 4. API Reference

All routes are prefixed by `/api/v1`.

### Ingestion API
* **`POST /calls`**
  * **Payload:** Multipart/form-data containing a `file` field (`.wav`, `.mp3`, or `.m4a` format, max 25 MB).
  * **Response:** `202 Accepted` returning the registered `call_id` and initial status `PENDING`.

### Retrieval APIs
* **`GET /calls`**
  * **Response:** `200 OK` returning a list of all calls ordered by upload time descending.
* **`GET /calls/{call_id}`**
  * **Response:** `200 OK` returning the call details joined with transcripts, summaries, tag entries, and event logs.
* **`GET /calls/{call_id}/audio`**
  * **Response:** Streams the raw audio file from the storage backend.

---

## 5. Tagging Schema, Prompt Design & Quality Evaluation

### 5.1 Tagging Schema

The LLM is instructed to classify every call into **7 structured tag categories** with a closed, enum-constrained vocabulary. The schema is defined in [`app/schemas/tag_schema.py`](backend/app/schemas/tag_schema.py) and injected directly into the system prompt — so the model never drifts from the values that the validation layer enforces.

| Category | What it captures | Allowed values |
|----------|-----------------|----------------|
| `outcome` | The direct result of the call | `won_deal_closed`, `follow_up_scheduled`, `not_interested`, `no_decision`, `unresolved_objection` |
| `sentiment` | Customer emotional tone | `positive`, `neutral`, `negative`, `mixed` |
| `intent_level` | Buying intent signal strength | `high`, `medium`, `low` |
| `objection_type` | Primary hesitation raised | `price_budget`, `timing_schedule`, `competitor_brand`, `no_immediate_need`, `no_purchasing_authority`, `no_objections_raised` |
| `next_step` | Agreed follow-up action | `demo_scheduled`, `send_proposal`, `call_again_follow_up`, `escalated_to_supervisor`, `closed_lost` |
| `compliance_flag` | Quality / audit risk flag | `possible_sensitive_data`, `inappropriate_language`, `none` |
| `product_interest` | Product lines mentioned (open list) | free-form strings |

**Justification:**
- **`outcome` + `next_step`** are the two highest-value fields for a sales manager. Knowing the result and the committed action is the minimum viable context to run a pipeline review.
- **`objection_type`** captures the single biggest blocker per call. Aggregating this across hundreds of calls exposes systemic product or pricing gaps.
- **`sentiment` + `intent_level`** are complementary signals: a prospect can be *positive but low-intent* (friendly but not ready to buy) or *negative but high-intent* (price-sensitive but motivated). Both dimensions together are far more predictive than either alone.
- **`compliance_flag`** is non-negotiable for regulated industries. Flagging calls with sensitive data or aggressive language enables an auditor queue without requiring humans to review every recording.
- **Closed vocabulary** is intentional: open-ended tags produce inconsistent distributions, making aggregation and trend analysis unreliable. New values should be added to the enum deliberately, not discovered ad-hoc in the database.

### 5.2 Prompt Design

The analysis system prompt is built dynamically in [`app/workers/tasks.py`](backend/app/workers/tasks.py) by the `_build_analysis_system_prompt()` function. Key design decisions:

1. **Role anchoring** — The LLM is assigned a concrete identity: *"You are an expert sales-call analyzer."* This reduces generic, hedge-heavy responses.

2. **Strict JSON schema output** — The prompt spells out the exact nested envelope (`summary` → `tags`) with field names, types, and constraints. No markdown, no code fences, no preamble. This makes parsing deterministic.

3. **Enum values derived from code, not prose** — The allowed values for each tag are generated from `ALLOWED_VALUES` at runtime. There is no hard-coded string in the prompt that can drift out of sync with the validator.

4. **Explicit handling of edge cases** — The prompt instructs the model to *"record numeric inconsistencies under `inconsistencies` rather than silently correcting them"*, producing auditable rather than hallucinated output.

5. **Language-aware output** — The model detects the transcript language and writes the summary in that language, making the system useful for multilingual sales teams without extra translation steps.

6. **JSON self-repair** — If the LLM returns malformed JSON, the worker retries once with an explicit repair instruction. A second failure falls back to a `needs_review=True` placeholder summary — the call is marked `COMPLETED`, not `FAILED`, so the pipeline never stalls on a single bad response.

Full prompt text: see `_build_analysis_system_prompt()` in [`backend/app/workers/tasks.py`](backend/app/workers/tasks.py).

### 5.3 Evaluating Tagging Quality Over Time

The platform is built with a four-layer quality flywheel:

**A. Gold Standard Dataset**
Maintain a curated set of 50–100 calls manually annotated by senior sales auditors. This dataset is the ground truth. Every prompt change must be tested against it before deployment.

**B. Automated Regression (CI/CD — LLM-as-a-Judge)**
On every pull request that touches a prompt or the analysis worker, a CI job runs the gold set through the production analyzer and compares outputs with a judge LLM. Any tag category dropping below **95% F1-score** blocks the merge.

```
New Prompt Draft
      │
      ▼
Test Run on Gold Set Dataset
      │
      ▼
Judge LLM Evaluator (Precision / Recall / F1 per category)
      │
      ├──[≥ 95%]──→ Deploy
      └──[< 95%]──→ Block + Alert
```

**C. Human Override Feedback Loop (already shipped)**
When a human auditor corrects a tag in the UI, the correction is saved to the `call_tag_overrides` table (implemented, tested). The override rate per category is a leading indicator of prompt degradation. A sustained override rate above ~10% on a category signals the need for a prompt revision.

**D. Semantic Drift Monitoring**
Weekly job that aggregates the distribution of every tag value across production calls. If `no_objections_raised` jumps from 35% to 80% without a corresponding business explanation, it indicates the model has started taking the path of least resistance — a classic prompt drift pattern.

**E. Prompt A/B Testing**
New prompt candidates are deployed to 10% of incoming calls. Override rate, confidence distribution, and latency are compared against the control before a full rollout.

> See [`docs/prompt_design.md`](docs/prompt_design.md) for the full extended documentation including the evaluation pipeline diagram.

---

## 6. Running Tests

The test suite contains 29 unit and integration tests covering validations, fake provider routing, worker tasks, error boundaries, and retrieve routes.

To execute tests:
```bash
# From altur/backend/
PYTHONPATH=. .venv/bin/pytest -v
```

---

## 7. Operational Manuals

Two complementary documents cover day-to-day operation and incident response:

### [PLAYBOOK.md](docs/PLAYBOOK.md) — Engineering & Operations Guide

> **Audience:** Engineers who build, configure, or maintain the platform.

Covers the full engineering lifecycle:

- Platform architecture diagram and pipeline walkthrough
- Environment reference (`LOCAL_DEV` vs `LOCAL_DOCKER` vs production)
- Provider setup guides (OpenAI Whisper STT, OpenAI/Qwen LLM, S3/MinIO storage)
- Worker queue operation (RQ + fakeredis in dev, real Redis in Docker)
- Database migration procedures (`alembic upgrade head`)
- Common operational workflows (re-ingesting a call, overriding a tag, exporting call data)
- Docker Compose bring-up and teardown commands

### [RUNBOOK.md](docs/RUNBOOK.md) — Incident Response Guide

> **Audience:** Engineers on-call or responding to production incidents.

Step-by-step diagnostic and recovery procedures organized by failure scenario:

| Code | Scenario |
|------|---------|
| RB-01 | Call stuck in `PENDING` |
| RB-02 | Call stuck in `TRANSCRIBING` or `ANALYZING` |
| RB-03 | Call in `FAILED` state |
| RB-04 | Worker not picking up jobs |
| RB-05 | Database connectivity failure |
| RB-06 | STT provider error (rate limit / timeout / auth) |
| RB-07 | LLM provider error (quota / malformed response) |
| RB-08 | Storage backend failure |
| RB-09 | High API latency or 5xx errors |

Each runbook entry includes diagnostic commands, a root-cause decision tree, and recovery steps.

---

## 8. Future Improvements / What I'd Improve Given More Time

### 8.1 Predictive Analytics & Operational Intelligence

> Full design: [`docs/predictive_analytics.md`](docs/predictive_analytics.md)

The structured data the platform already persists (transcript turns, sentiment scores, intent scores, tag values, human overrides, per-stage timestamps) is immediately usable as a feature store for predictive models. The planned analytical layer answers four families of questions:

| # | Question | Approach |
|---|----------|----------|
| A | **Win probability** — how likely is this prospect to accept? | Propensity model trained on `CallTag` outcomes + `Summary` signals |
| B | **Loss driver analysis** — what patterns precede a deal loss? | Supervised loss-reason classifier + feature importance |
| C | **Bot misbehaviour detection** — is the conversational agent going off-script? | Interaction-quality anomaly model over transcript turns |
| D | **Provider SLO monitoring** — are STT/LLM responding in time? | `CallEvent` latency extraction + alerting thresholds |

Design stance: **LLMs as feature extractors + classical ML for calibrated probability estimates** — not end-to-end LLM prediction, which is expensive and poorly calibrated at scale.

### 8.2 Software Factory — Self-Improving Platform

> Full design: [`docs/software_factory.md`](docs/software_factory.md)

The longer-term roadmap treats Call Analyzer not as a finished product but as a **production line that manufactures its own improvements**. Every request leaves measurable evidence (latency, tag quality, human correction rate, token cost). The factory runs a weekly continuous improvement loop:

```
MEASURE → ANALYZE → PROPOSE → IMPLEMENT → VERIFY → PROMOTE
   ▲                                                    │
   └────────────────────────────────────────────────────┘
```

Key capabilities in this track:

- **Instrumented measurement points** — per-stage metrics (STT latency, LLM latency, token cost, parse success rate) emitted on every call automatically.
- **Automated prompt regression CI** — every prompt change runs against the gold set; F1 drops block the merge.
- **Agent-assisted prompt authoring** — LLM agents draft and evaluate prompt candidates, narrowing human review to judgment calls.
- **Improvement ledger** — immutable audit of every change with its measured metric delta, making improvements reversible and auditable.

### 8.3 Other Technical Improvements

- **Speaker diarization** — production Whisper Diarization or Deepgram would add speaker labels automatically.
- **Real-time streaming** — replace status polling with WebSocket push for instant UI updates.
- **PostgreSQL full-text search** — replace `ILIKE` with `tsvector` indexes for sub-100ms transcript search at scale.
- **E2E browser tests** — Playwright suite covering the full upload-to-detail user flow.
- **Authentication** — JWT-based auth with per-user call isolation (`owner_id` column already exists in the schema).
- **Multi-language STT routing** — auto-detect transcript language and route to the best regional STT model.
