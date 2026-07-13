# Call Analyzer - Altur Take-home

Sales call transcription suite, automated semantic analysis, and quality assurance (QA) control.

## 1. Overview & Screenshots
> 🚧 Completed in Phase 7.

## 2. Architecture
* **Event-Driven / Decoupled Architecture:** The asynchronous pipeline isolates the ingestion (`POST /calls`), transcription (STT), and analysis (LLM) using a task queue (RQ) and dedicated workers.
* **Execution Modes:**
  * **LOCAL_DEV:** SQLite for the database, RQ in burst mode (synchronous `fakeredis`), deterministic `FakeSTT` and `FakeLLM` providers loaded from fixtures, and local disk storage.
  * **LOCAL_DOCKER:** PostgreSQL, Redis, configured providers, and local disk storage in Docker Compose.
  * **CLOUD:** Managed PostgreSQL, managed Redis, S3 for storage, and real OpenAI APIs.

## 3. Quickstart (LOCAL_DEV)
> 🚧 Completed in Phase 10.

## 4. Running with Docker
> 🚧 Completed in Phase 10.

## 5. Environment Variables
The project uses a single environment variable contract configured using Pydantic Settings.
* See [env.example](.env.example) for more details.
> 🚧 Completed in Phase 10.

## 6. API Reference
> 🚧 Completed in Phases 2 and 6.

## 7. Tagging Schema & Prompt Design
The analyzer uses a structured scheme of 7 sales tag categories.
* See [prompt_design.md](docs/prompt_design.md) for details on prompt design and quality evaluation.

## 8. Testing
> 🚧 Completed in Phase 9.

## 9. Error Handling & State Machine
The system implements a state machine to perform atomic transitions and guarantee task queue idempotency.
* **States:** `PENDING ➔ TRANSCRIBING ➔ TRANSCRIBED ➔ ANALYZING ➔ DONE / FAILED`
> 🚧 Completed in Phase 8.

## 10. Deployment (Heroku)
> 🚧 Completed in Phase 10.

## 11. Assumptions & Trade-offs
> 🚧 Completed in Phase 10.

## 12. Roadmap (Future Improvements)
> 🚧 Completed in Phase 10.
