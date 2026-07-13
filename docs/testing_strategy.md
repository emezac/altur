# Testing Strategy

This document details the test framework, test isolation boundaries, and execution steps for the Call Analyzer suite.

---

## 1. General Quality Approach

The primary objective is to maintain high code reliability across database interactions, file storage, task queuing, and external API mappings. 

* **Determinism:** Tests avoid live network requests. Fake provider implementations mimic external APIs by returning local JSON files loaded from static fixtures.
* **Database Isolation:** Tests run on an in-memory SQLite connection (`sqlite:///`). Each test is wrapped in an atomic transaction that is completely rolled back upon completion, preventing data leakage between runs.
* **Storage Isolation:** Audio file persistence is redirected to temporary directories that are cleaned up automatically by pytest fixtures.

---

## 2. The Test Pyramid

The codebase is validated across three distinct testing scopes:

```
          ▲
         / \
        /   \     Pipeline Integration Tests (e.g., test_pipeline.py)
       /  I  \    - Decoupled task orchestration & Error boundaries
      /───────\
     /    A    \  API Integration Tests (e.g., test_upload_flow.py)
    /     P     \ - Ingestion validation, upload status, retrieval JSONs
   /─────────────\
  /       U       \ Unit Tests (e.g., test_file_validation.py)
 /_________________\ - File signatures, extensions, mock provider routing
```

### A. Unit Tests
* Validate standalone utility classes and service logic.
* Coverage includes:
  * **File Validator:** Verifying file extension checks, file size constraints, and binary byte signature checks.
  * **Fake Providers:** Verifying routing logic (asserting that filenames like `call_01.wav` correctly yield the corresponding Nube Ventas transcripts, and that text keywords match correct LLM summaries).

### B. API Integration Tests
* Validate FastAPI routes and controllers.
* Coverage includes:
  * **Upload Flow (`POST /calls`):** Asserting that valid WAV/MP3 uploads return `202 Accepted` and register database objects.
  * **Retrieval (`GET /calls`, `GET /calls/{id}`):** Validating JSON schemas and mapping relationships.
  * **Audio Ingestion Errors:** Testing extensions (e.g., uploading `.txt` returns `400`), size limits, and database rollback verification (confirming files are deleted from disk if the DB write fails).

### C. Pipeline Tests
* Validate worker orchestration tasks: `transcribe_call` and `analyze_call`.
* Assert status transition audits (`PENDING ➔ TRANSCRIBING ➔ TRANSCRIBED ➔ ANALYZING ➔ COMPLETED`) and database entries for transcripts, summaries, and EAV tags.
* Verify error boundaries (mocking external service crashes translates status to `FAILED` and appends `ERROR` event logs).

---

## 3. Test Fixtures

Test fixtures under `tests/conftest.py` define reusable mocks:

* `db`: In-memory SQLite connection pinned per test case.
* `client`: FastAPI TestClient utilizing the test database session.
* `temp_storage`: Overrides local storage path pointing to a temporary pytest path.
* `mock_tasks_db_session`: Injects the transaction session into tasks and disables `db.close()` so inline worker executions run inside the test transaction.

---

## 4. Test Execution

Execute all tests from the `backend/` directory:
```bash
PYTHONPATH=. .venv/bin/pytest -v
```
