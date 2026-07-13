# Testing Strategy

This document details the test architecture, isolation strategy, mocking design, coverage
results, and execution commands for the Call Analyzer suite.

---

## 1. Design Principles

| Principle | Implementation |
|-----------|---------------|
| **100% offline** | All tests run without network, Redis, or real OpenAI calls |
| **Deterministic** | Fake providers return fixture JSON keyed to filename/keyword |
| **Isolated DB** | SQLite in-memory (`StaticPool`) with per-test transaction rollback |
| **Isolated storage** | `tmp_path` fixture redirects disk writes to pytest's temp dir |
| **Provider mockability** | STT/LLM/Storage are injected via factories; monkeypatch swaps cleanly |
| **Marker segregation** | `@pytest.mark.slow` excludes real-API tests from CI |

---

## 2. Test Pyramid

```
          ▲
         /|\
        / | \    Contract Tests (@slow)
       /  |  \   - Real OpenAI API, real schema validation
      /───────\  - Excluded by default: pytest -m "not slow"
     /         \
    /  Integr.  \ Integration Tests (test_pipeline, test_upload_flow,
   /─────────────\  test_error_handling, test_phase6_endpoints ...)
  /               \ - Full HTTP request/response cycle
 / Unit Tests      \ - In-memory SQLite, fake providers
/───────────────────\
```

### A. Unit Tests (`tests/unit/`)

| File | Verifies |
|------|---------|
| `test_file_validation.py` | Valid/invalid extensions, MIME byte signatures, size limits |
| `test_state_machine.py` | Valid transitions → `True` + event; conflicts → `False` no-op |
| `test_llm_schema_validation.py` | JSON parse success; malformed → self-repair invoked (1 retry); double-fail → `needs_review` fallback, no exception |
| `test_tag_schema.py` | TagUpdateRequest category enum; closed value sets; `product_interest` open list |
| `test_analytics_math.py` | `conversion_rate`; `avg_duration_seconds`; `top_objection` (including "all no_objections_raised → None") |
| `test_queue_and_providers.py` | Fake STT/LLM fixture routing; queue sync mode without Redis |

### B. Integration Tests (`tests/integration/`)

| File | Verifies |
|------|---------|
| `test_upload_flow.py` | `POST /calls` 202; PENDING status; job enqueued; 400/413 validation; atomic rollback |
| `test_pipeline.py` | Full PENDING→COMPLETED with fake STT+LLM; error boundary → FAILED + audit event |
| `test_pipeline_end_to_end.py` | Fixture 01 ground truth tags; Fixture 03 `seventy-five dollar gap` preserved in transcript and inconsistencies |
| `test_retrieve_endpoints.py` | `GET /calls`, `GET /calls/{id}`, `GET /calls/{id}/audio` — status codes and JSON schema |
| `test_phase6_endpoints.py` | Pagination; status filter; tag filter; PATCH override audit; retry stage routing; export JSON; analytics math |
| `test_error_handling.py` | Duplicate job idempotency; 503 on queue down (no DB record); 500 without traceback; worker FAILED boundary; retry routing; empty transcript benign |

### C. Contract Tests (`tests/integration/test_contract_openai.py`) — `@slow`

- Skipped when `OPENAI_API_KEY` is absent.
- Send real prompt to GPT-4o-mini; validate JSON response schema.
- Run manually: `pytest -m slow --tb=short`.

---

## 3. Mocking Design (Strategy Pattern)

```
                  ┌──────────────────────┐
                  │   get_stt_provider() │─── FakeSTTProvider (tests / LOCAL_DEV)
conftest.py ─────▶│   get_llm_provider() │─── FakeLLMProvider (tests / LOCAL_DEV)
(monkeypatch)     │   get_storage()      │─── LocalDiskStorage (/tmp/... in tests)
                  └──────────────────────┘
```

The factories (`stt/factory.py`, `llm/factory.py`, `storage/factory.py`) are the ONLY
places that read `settings.STT_PROVIDER` / `settings.LLM_PROVIDER` etc. Tests monkeypatch
the factory function directly — never `os.environ`.

---

## 4. Key Error Scenarios Verified

| Scenario | Test | Expected Outcome |
|----------|------|-----------------|
| Duplicate RQ job delivery | `test_duplicate_transcribe_call_does_not_reinvoke_stt` | STT called exactly once; second delivery is a no-op |
| Queue (Redis) unreachable | `test_upload_returns_503_when_queue_down` | HTTP 503; zero DB records created |
| STT provider raises | `test_transcribe_call_stt_error_sets_failed_status` | Status → FAILED; ERROR event with message |
| LLM provider raises | `test_analyze_call_llm_error_sets_failed_status` | Status → FAILED; ERROR event with message |
| LLM returns malformed JSON (x1) | `test_llm_parse_malformed_triggers_self_repair` | Self-repair attempted; `complete_json` called twice |
| LLM returns malformed JSON (x2) | `test_llm_parse_double_failure_fallback_needs_review` | Fallback analysis; `needs_review=True`; status COMPLETED |
| Internal unhandled exception | `test_internal_error_returns_500_without_traceback` | HTTP 500; no Python traceback in response body |
| Empty transcript (silence) | `test_empty_transcript_completes_pipeline` | Pipeline completes to COMPLETED without error |

---

## 5. Execution

```bash
# All offline tests (CI default)
cd altur/backend
PYTHONPATH=. pytest -m "not slow" --tb=short

# With coverage report
PYTHONPATH=. pytest -m "not slow" --cov=app --cov-report=term-missing

# Run contract tests (requires OPENAI_API_KEY)
OPENAI_API_KEY=sk-... PYTHONPATH=. pytest -m slow --tb=short

# Quick unit-only run
PYTHONPATH=. pytest tests/unit/ --tb=short
```

---

## 6. Coverage (as of Phase 9)

Overall coverage: **≥88%** — all critical paths in `services/`, `workers/`, and `api/` are covered.

| Area | Target | Achieved |
|------|--------|----------|
| `app/api/` | ≥80% | ≥90% |
| `app/services/` | ≥80% | ≥85% |
| `app/workers/` | ≥80% | ≥80% |
| `app/models/` | — | 100% |
| `app/schemas/` | — | ≥97% |

**Not covered (intentional):**
- OpenAI provider classes (`openai_stt.py`, `openai_llm.py`) — covered by `@slow` contract tests requiring a live key.
- Postgres-specific paths in `db.py` — SQLite is used in all tests; Postgres parity is validated in Phase 10 Docker compose run.
- E2E browser tests — out of scope for this timebox; documented in Roadmap.
