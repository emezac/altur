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

## 5. Running Tests

The test suite contains 29 unit and integration tests covering validations, fake provider routing, worker tasks, error boundaries, and retrieve routes.

To execute tests:
```bash
# From altur/backend/
PYTHONPATH=. .venv/bin/pytest -v
```
