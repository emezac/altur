# Software Factory — Self-Improvement Strategy

> **Audience:** Platform engineers, ML engineers, and engineering leads.
> **Scope:** How to evolve Call Analyzer into a **self-improving application** using the *software factory* concept: which exact code must be modified to become a **measurement point**, how metrics are reviewed automatically, and how accumulated improvements are evaluated and shipped in continuous improvement cycles.
> **Related:** [`predictive_analytics.md`](./predictive_analytics.md) · [`prompt_design.md`](./prompt_design.md) · [`architecture_scale.md`](./architecture_scale.md) · [`testing_strategy.md`](./testing_strategy.md)

---

## 1. Concept: the app as a software factory

A **software factory** treats the application not as a finished product but as a **production line that manufactures its own improvements**. Every request that flows through the system leaves behind measurable evidence (latency, quality, cost, human corrections). The factory:

1. **Measures** — instrumented checkpoints emit metrics automatically on every call.
2. **Analyzes** — a scheduled reviewer aggregates metrics per cycle and detects regressions, drift, and opportunities.
3. **Proposes** — signal-to-improvement rules turn metric patterns into a ranked improvement backlog.
4. **Implements** — changes ship as *versioned artifacts* (prompt versions, provider configs, model choices, code), increasingly authored with agent-assisted coding (Claude Code / CI agents).
5. **Verifies** — every candidate must pass automated gates (unit tests, golden-set evaluation, canary metrics) before promotion.
6. **Learns** — an *improvement ledger* records each change and its measured metric delta, so accumulated improvements are auditable and reversible.

This is the classic **PDCA / kaizen loop** industrialized with CI/CD and LLM evaluation:

```
        ┌──────────────────────────────────────────────────────────┐
        │                    IMPROVEMENT CYCLE (weekly)             │
        │                                                          │
   ┌────▼─────┐   ┌───────────┐   ┌────────────┐   ┌────────────┐  │
   │ MEASURE  │──►│  ANALYZE  │──►│  PROPOSE   │──►│ IMPLEMENT  │  │
   │ metric   │   │ scheduled │   │ backlog    │   │ versioned  │  │
   │ points   │   │ reviewer  │   │ generator  │   │ artifacts  │  │
   └────▲─────┘   └───────────┘   └────────────┘   └─────┬──────┘  │
        │                                                 │         │
        │         ┌────────────┐   ┌────────────┐         │         │
        └─────────│  PROMOTE   │◄──│   VERIFY   │◄────────┘         │
                  │ + ledger   │   │ tests+eval │                   │
                  └────────────┘   │ +canary    │                   │
                                   └────────────┘                   │
        └──────────────────────────────────────────────────────────┘
```

Everything below maps this loop onto the **actual codebase**.

---

## 2. Measurement points — the exact code to modify

The factory starts by turning existing hot paths into instrumented checkpoints. The platform already has the two primitives needed: an append-only audit stream (`CallEvent`) and provenance stamping (`prompt_version`, `llm_provider`, `llm_model`, `stt_provider`). The changes below make measurement **automatic and uniform**.

### 2.1 New module: `app/core/metrics.py` (create)

Single entry point every other measurement point calls. Keeps instrumentation one-line at call sites.

```python
# app/core/metrics.py (new)
@contextmanager
def measure(stage: str, **labels):
    """Times a block and emits a metric event: name, duration_ms, status, labels."""
    ...

def emit(name: str, value: float, **labels):
    """Emits a counter/gauge metric with labels (provider, model, prompt_version...)."""
    ...
```

Backing store (phase 1): a `metric_events` table mirroring `CallEvent` (append-only: `name`, `value`, `labels` JSON, `created_at`). Phase 2: also export to Prometheus/OTel — the call sites don't change, only the sink.

### 2.2 Worker pipeline: `app/workers/tasks.py` (modify — highest-value point)

This file executes 100% of the STT/LLM work, so it is the factory's primary sensor.

| Function | Instrumentation to add | Metric emitted |
|----------|------------------------|----------------|
| `transcribe_call` | Wrap `stt.transcribe(...)` in `measure("stt.transcribe", provider=..., model=...)` | STT latency, error rate per provider |
| `analyze_call` | Wrap `llm.complete_json(...)` in `measure("llm.complete", provider=..., model=..., prompt_version=...)` | LLM latency, error rate per provider/prompt |
| `analyze_call` — first `json.loads` failure branch | `emit("llm.schema_repair", 1, ...)` | **Self-repair rate** — prompt quality leading indicator |
| `analyze_call` — needs-review fallback branch | `emit("llm.schema_fallback", 1, ...)` | **Hard schema failure rate** — regression alarm input |
| `analyze_call` — after `Summary` persisted | `emit("analysis.confidence", tags_data["outcome_confidence"], ...)` | Confidence distribution per prompt_version |
| Both error boundaries (`except`) | `emit("pipeline.failed", 1, step=...)` | Failure rate per stage |
| `_build_analysis_system_prompt` | Move prompt text to a versioned artifact (see §5.1) and stamp the real version instead of the hardcoded `prompt_version="v1"` | Enables per-version comparison — the core of the loop |

### 2.3 Provider factories: `app/services/llm/factory.py`, `app/services/stt/factory.py` (modify)

Wrap the returned provider in an **instrumentation decorator** so every provider (fake/OpenAI/Qwen, and any future one) is measured identically without touching provider code:

```python
# get_llm_provider() returns InstrumentedLLM(provider, labels={provider, model})
```

Metrics: per-call latency, exception class, retry count, (when available) token usage → **cost per call**. This is also the hook where a **circuit breaker / failover** acts on the same measurements (see `predictive_analytics.md` §8).

### 2.4 Human feedback: `app/services/calls_service.py::apply_tag_override` (modify)

The single most valuable quality signal — every human override is a labeled model error.

- Add `emit("tag.override", 1, category=..., from_value=model_tag, to_value=..., prompt_version=...)`.
- **KPI derived:** override rate per tag category per `prompt_version`. A rising override rate is the factory's #1 trigger for a prompt-improvement cycle.

### 2.5 API edge: `app/api/calls.py::upload_call` (modify)

- `measure("api.upload")` around the handler body; `emit("upload.rejected", 1, reason=...)` on each validation failure (`validate_file_size`, `validate_file_format`, queue pre-flight 503).
- **KPI derived:** ingestion latency, rejection taxonomy (are users hitting limits we should revisit?).

### 2.6 State machine: `app/services/state_machine.py::transition` (modify)

- `emit("state.transition", 1, from=..., to=...)` on success; `emit("state.rejected", 1, ...)` on rejected (duplicate) transitions.
- **KPI derived:** stage dwell times (time between transitions per call), duplicate-delivery rate, stuck-job detection input.

### 2.7 Aggregation & exposure: `app/api/analytics.py` (extend)

- New endpoint `GET /api/v1/analytics/factory` returning the per-cycle KPI snapshot (see §3) computed from `metric_events` — consumed by the reviewer job, the dashboard, and CI gates.

> **Non-goal:** do *not* scatter ad-hoc logging. All points call `app/core/metrics.py`; the sink and the schema stay uniform, which is what makes automated review possible.

---

## 3. Metrics catalog → cycle KPIs

| KPI (per cycle, per version) | Source metric | Improvement signal when… |
|------------------------------|---------------|--------------------------|
| p50/p95 STT & LLM latency | `stt.transcribe`, `llm.complete` | p95 grows > budget → provider/perf work |
| Pipeline failure rate | `pipeline.failed` | > SLO → reliability work |
| Schema self-repair rate | `llm.schema_repair` | Rising → prompt tightening candidate |
| Schema fallback (needs_review) rate | `llm.schema_fallback` | > 0.5% → prompt/provider regression, block promotions |
| Tag override rate (per category) | `tag.override` | Rising → tagging prompt or schema redesign |
| Confidence distribution | `analysis.confidence` | Drifting down → model/prompt drift |
| Upload rejection taxonomy | `upload.rejected` | Concentrated cause → UX/limits change |
| Stage dwell time | `state.transition` | Queue wait growing → scaling work |
| Cost per analyzed call | provider token/pricing labels | Above target → cheaper model/provider experiment |
| Duplicate-delivery rate | `state.rejected` | High → queue tuning |

Each KPI carries `prompt_version`, `llm_model`, and `stt_provider` labels, so **every question is a group-by**: "did prompt v3 reduce overrides vs v2?" is one query.

---

## 4. Automated review: the cycle reviewer

A scheduled job (cron / RQ scheduler / CI nightly) closes the "automatic review" requirement:

1. **Snapshot** — query `metric_events` for the window (e.g., last 7 days) grouped by version labels; persist a `factory_cycle` row (cycle id, KPI JSON, window).
2. **Compare** — diff against the previous cycle and against declared budgets (SLOs + quality targets checked into the repo, e.g., `docs/budgets.yaml`).
3. **Classify** — each KPI is `improved / stable / regressed` with statistical guard (min sample size before judging).
4. **Report & alarm** — publish the cycle report to the dashboard endpoint; regressions above threshold raise the operator alarms defined in `predictive_analytics.md` §8.
5. **Feed the backlog** — regressed/opportunity KPIs are mapped to improvement candidates via the rule table in §5.

This reviewer is intentionally dumb-and-deterministic first (rules, budgets); an LLM analyst summarizing the cycle report for humans is a later, additive layer.

---

## 5. Implementing improvements as versioned artifacts

Improvements only accumulate safely if every changeable behavior is **versioned, testable, and reversible**.

### 5.1 Prompts as versioned artifacts (refactor `tasks.py`)

- Move `_build_analysis_system_prompt` output into `app/prompts/analysis/v1.py` (or `.md` templates) with a registry: `get_prompt("analysis")` returns `(text, version)`.
- `analyze_call` stamps the **real** version into `Summary.prompt_version` (replacing the hardcoded `"v1"`).
- A new prompt = a new file + registry entry, selectable per-environment / per-canary-percentage via config. Rollback = flipping the registry default.

### 5.2 Providers & models as config experiments

Already in place via factories + `.env` (`LLM_PROVIDER`, `QWEN_MODEL`, …). Add **canary routing** in the factory (N% of calls to candidate provider/model, labeled) so cost/quality experiments run inside the same measurement fabric.

### 5.3 Code changes through the factory gate

Agent-assisted or human, every change passes the same gates in CI:

| Gate | Implementation (exists / to add) |
|------|----------------------------------|
| Unit + integration tests | `pytest` suite (79 tests) — exists |
| Schema validation tests | `tests/unit/test_llm_schema_validation.py` — exists |
| **Golden-set evaluation** | To add: fixed set of transcripts + expected tags; run candidate prompt/model offline; block if agreement drops (see `prompt_design.md`) |
| **Budget check** | To add: CI job queries `/analytics/factory` post-canary; block promotion if any KPI regressed beyond budget |
| Canary + rollback | Registry/config flip; ledger records outcome |

---

## 6. The improvement ledger — evaluating accumulated improvements

A small append-only table (or `docs/IMPROVEMENT_LEDGER.md` in phase 1) records every promoted change:

| Field | Example |
|-------|---------|
| cycle_id | `2026-W29` |
| change | `prompt analysis v2 → v3: explicit enum values in schema block` |
| trigger KPI | `tag.override rate (objection) 14% → target <8%` |
| result KPI delta | `override 14% → 6.5%; schema_fallback 0.8% → 0.1%` |
| verdict | `kept` / `rolled back` |

This is what makes improvement **cumulative** rather than churn: each cycle's report shows the KPI trend line annotated with ledger entries, so the team (and an auditor) can see exactly which change produced which measured gain — and compounding gains over cycles are provable, not anecdotal.

---

## 7. Cycle cadence

| Cadence | Activity |
|---------|----------|
| Continuous | Metric points emit on every call; alarms on SLO breach |
| Nightly | Reviewer snapshot + golden-set eval of any open canary |
| Weekly | Cycle close: report, backlog re-rank, promote/rollback decisions, ledger update |
| Quarterly | Budget/SLO revision; prune stale prompt versions and dead experiments |

---

## 8. Guardrails

- **Humans promote, machines propose.** The factory generates candidates and evidence; promotion of prompts/models affecting compliance or PII behavior requires human approval.
- **Minimum sample sizes** before any KPI verdict — no reacting to noise.
- **One variable per experiment** (prompt *or* model *or* provider), enforced by labeling.
- **Rollback is one config flip**, never a code revert under pressure.
- **The judge is audited**: golden set refreshed with real overridden calls each cycle so evaluation tracks reality.

---

## 9. Phased adoption

| Phase | Deliverable | Touches |
|-------|-------------|---------|
| **1 — Instrument** | `app/core/metrics.py`, `metric_events` table, instrumentation in `tasks.py`, factories, `apply_tag_override`, `upload_call`, `transition` | Small, mechanical |
| **2 — Review** | Reviewer job + `GET /analytics/factory` + budgets file + cycle report | Small |
| **3 — Version** | Prompt registry (real `prompt_version`), canary routing in factories, golden-set eval in CI | Medium |
| **4 — Ledger & gates** | Improvement ledger, CI budget gate, weekly cycle ceremony | Small |
| **5 — Agentize** | Agent-assisted backlog→PR generation flowing through the same gates | Incremental |

Phase 1 alone already converts the app into a measured system; each later phase only adds review, versioning, and governance on top of the same measurement fabric.
