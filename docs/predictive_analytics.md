# Predictive Analytics & Operational Intelligence

> **Audience:** ML / data engineers, backend engineers, and product owners.
> **Scope:** How to build an analytical + predictive layer on top of Call Analyzer that (1) predicts customer behavior (accept / churn / loss reasons), (2) detects when a conversational bot is misbehaving and recommends prompt/tool fixes, and (3) monitors STT/LLM providers to guarantee they serve requests in time and raise immediate alarms to operators.
> **Related:** [`architecture_scale.md`](./architecture_scale.md) · [`prompt_design.md`](./prompt_design.md) · [`PLAYBOOK.md`](./PLAYBOOK.md) · [`RUNBOOK.md`](./RUNBOOK.md)

---

## 1. Goals & the questions we answer

This layer turns the per-call analysis the platform already produces into **forward-looking, decision-grade signals**. It answers four families of questions:

| # | Question | Model | Consumer |
|---|----------|-------|----------|
| A | How likely is this prospect to **accept the product**? | Win / acceptance propensity | Reps, sales managers |
| B | **Why do deals fail** — what pattern precedes a loss? | Loss-reason / risk driver model | Enablement, product |
| C | Is a **conversational bot misbehaving**, and how do we fix it (prompt vs. tools)? | Interaction-quality / anomaly model | Bot designers, prompt engineers |
| D | Are **providers (STT/LLM) serving requests in time and form**, and when do we alarm? | SLO monitoring + anomaly detection | On-call operators, admins |

Design stance: **hybrid, interpretable, human-in-the-loop.** LLMs are excellent feature extractors and judges but are poorly calibrated probability estimators and expensive to run at scale. We therefore combine an LLM feature/judge layer with classical, calibrated ML for the numeric prediction, and never let a model take an irreversible action without a human or a guardrail.

---

## 2. We already have the raw material

No new capture pipeline is needed to start — the predictive layer is fed by data the app persists today:

| Source (table / field) | Signal it provides |
|------------------------|--------------------|
| `Call` (`duration_seconds`, `uploaded_at`, `status`) | Call length, recency, terminal outcome of processing |
| `Transcript.turns` (`speaker`, `start`, `end`, `text`) | Turn-taking, talk/listen ratio, interruptions, silence gaps, question count |
| `Transcript.language`, `stt_confidence` | Language routing, transcription reliability |
| `Summary.insights` (`sentiment_score`, `intent_score`, `buying_signals`, `risks`, `inconsistencies`, `tone_notes`, `needs_review`) | LLM-extracted semantic features |
| `CallTag` (`tag_category`, `tag_value`, `confidence`, `source`) | Structured outcome / objection / next-step tags + model confidence + **human overrides** |
| `CallEvent` (`event_type`, `payload`, `created_at`) | Per-stage timestamps, error steps — the backbone of latency & SLO metrics |
| `Summary.llm_provider / llm_model / prompt_version`, `Transcript.stt_provider / stt_model` | Provenance for A/B, drift, and per-provider quality attribution |

> The **override signal** (`CallTag.source = 'override'`) is gold: every time a human corrects a model tag, we get a free, high-quality label for supervised learning and a direct measure of model error.

---

## 3. Model portfolio

### 3.1 Model A — Deal acceptance (win) propensity

**Target.** `P(win)` for a call/opportunity, where "win" is derived from the terminal `outcome` tag (`won_deal_closed` / `follow_up_scheduled` as positive momentum vs. `not_interested` / `unresolved_objection`) and, ideally, joined to a CRM close event for hard ground truth.

**Approach (recommended): two-stage hybrid.**
1. **Feature extraction (LLM + deterministic):** the analysis worker already emits `sentiment_score`, `intent_score`, `buying_signals`, `risks`, `objection_type`. Augment with cheap deterministic conversational features (see §4).
2. **Calibrated classifier:** a gradient-boosted tree (XGBoost / LightGBM) or logistic regression on the feature vector. Trees handle mixed tabular features and non-linear interactions well and remain explainable via SHAP. Apply **probability calibration** (Platt / isotonic) so `0.8` really means 80%.

**Why not "just ask the LLM for a number":** LLM-emitted scores are uncalibrated, unstable across `prompt_version`, and can't be back-tested cheaply. Use the LLM for language understanding; use ML for the probability.

**Output:** `win_probability` (0–1, calibrated), top ± SHAP drivers ("high intent_score", "unresolved price objection"), and a confidence band.

### 3.2 Model B — Loss-reason / failure driver model

**Purpose.** Not just *if* a deal fails but *why*, so enablement and product can act on patterns.

- **Descriptive layer:** aggregate `objection_type`, `risks`, `inconsistencies`, and `compliance_flag` across lost calls to rank recurring failure themes (e.g., "price_budget + no_purchasing_authority" co-occurrence).
- **Predictive layer:** a multi-label classifier predicting the dominant loss driver from mid-call features, enabling **in-flight coaching** ("authority not confirmed — ask for the decision maker").
- **Causal caution:** these are correlational drivers. Validate with holdouts and, where possible, controlled experiments (e.g., a new objection-handling script) before claiming causality.

### 3.3 Model C — Bot interaction quality & misbehavior detection

For calls/chats handled by an automated agent, detect when the **bot itself** is the reason interaction degrades, and recommend whether the fix is a **prompt change** or a **tool/design change**.

**Signals of misbehavior (features):**
- Repetition / looping (same intent restated), ignored customer questions, topic drift.
- Rising negative `sentiment_score` trajectory after bot turns; customer interruptions/overrides.
- Hallucination & policy signals: `inconsistencies`, `compliance_flag = possible_sensitive_data`, `needs_review = true`.
- Tool-failure fingerprints: turns where the bot promises data it never returns, or `CallEvent` errors tied to a tool call.

**Scoring method — LLM-as-a-judge + rubric:** a stronger evaluator model scores each bot turn against a fixed rubric (relevance, grounding, policy adherence, goal progress) and emits a **misbehavior class** plus a **remediation recommendation**:

| Misbehavior class | Likely root cause | Recommended fix |
|-------------------|-------------------|-----------------|
| Off-topic / ignores user | Under-specified prompt, weak instruction hierarchy | **Prompt**: tighten system role, add refusal/redirect rules |
| Hallucinated facts / numbers | Missing grounding, no retrieval | **Tools**: add RAG / lookup tool; forbid unsourced claims |
| Fails to complete task | Missing capability | **Tools**: add the action (booking, CRM write) the bot keeps faking |
| Repetition / looping | No state tracking | **Design**: add conversation-state memory / step tracker |
| Leaks / over-collects PII | No guardrail | **Design**: pre-output PII filter, policy prompt |

The output feeds a **design feedback loop** (§8): recommendations are grouped by `prompt_version` / tool config so we can measure whether a change actually improved interaction quality.

### 3.4 Model D — Provider SLO monitoring & anomaly detection

See §9 — this is the operational guarantee that STT/LLM providers serve requests in time and form, with immediate alarms.

---

## 4. Feature engineering

Most predictive lift comes from features that are **cheap and deterministic**, computed straight from `Transcript.turns` and `CallEvent` — no extra LLM cost:

**Conversational dynamics (from `turns`):**
- Talk/listen ratio per role, longest monologue, number of customer questions, interruption count, average response latency, silence gaps, call `duration_seconds`.
- Sentiment **trajectory** (slope, last-third average) rather than a single score — momentum predicts outcome better than a snapshot.

**Semantic (from `Summary.insights` / `CallTag`):**
- `intent_score`, `sentiment_score`, counts of `buying_signals` vs. `risks`, presence of `objection_type`, `compliance_flag`.
- `stt_confidence` and `needs_review` as data-quality features (low-quality transcripts should down-weight predictions).

**Provenance / context:** `llm_model`, `prompt_version`, `stt_provider`, `language`, time-of-day, rep/team id (if available).

> Serve these through a small **feature store** (even a `call_features` table to start) so training and online scoring read the *same* definitions — eliminating train/serve skew, a top cause of silent model failure.

---

## 5. Labels & ground truth

| Label | Source | Quality |
|-------|--------|---------|
| Won / lost | CRM close event (best) or terminal `outcome` tag | High / medium |
| Correct tag | `CallTag.source = 'override'` (human correction) | High |
| Bot misbehavior | LLM-judge score **validated** against a human-labeled golden set | Medium, needs audit |
| Provider breach | `CallEvent` timing vs. SLO threshold | Deterministic |

Bootstrap with **weak supervision**: use existing tags/overrides as noisy labels, then progressively replace with CRM truth and a curated golden set. Always keep a **held-out golden set** the models never train on, for honest evaluation.

---

## 6. System architecture & integration

The predictive layer plugs into the existing event-driven pipeline as **one more stage after `analyze_call`**, plus an always-on monitoring service. It reuses the state machine, queue, and audit trail.

```
  analyze_call (COMPLETED)
        │  emits event: call.analyzed
        ▼
  ┌────────────────────┐     reads      ┌──────────────────┐
  │  score_call worker │ ─────────────► │  Feature store    │
  │  (Predictive)      │                │  (call_features)  │
  └─────────┬──────────┘                └──────────────────┘
            │ writes Prediction rows          ▲
            ▼                                 │ same feature defs
  ┌────────────────────┐   registry     ┌──────────────────┐
  │  Model Registry    │◄──────────────►│  Batch training   │
  │  (versioned)       │                │  + eval (offline) │
  └────────────────────┘                └──────────────────┘

  CallEvent stream ─► Metrics collector ─► SLO monitor ─► Alarms (SSE / Slack / PagerDuty)
```

**Additions (proposed):**
- **Table `prediction`**: `call_id`, `model_name`, `model_version`, `target`, `score`, `calibrated`, `top_drivers` (JSONB), `created_at`. Append-only, like `CallEvent`.
- **Table `provider_metric`** (or a time-series sink): `provider`, `stage`, `latency_ms`, `status`, `created_at`.
- **Worker `score_call`**: consumes `call.analyzed`, builds features, scores Models A–C, persists `prediction` rows. Idempotent via the same conditional-update pattern used elsewhere.
- **Endpoints**: `GET /api/v1/calls/{id}/predictions`, `GET /api/v1/analytics/predictions` (aggregates), and `GET /api/v1/ops/slo` for the monitoring dashboard.
- **Scoring modes**: **batch** (nightly retrain + backfill) and **online** (score-on-completion for live calls); optional **streaming/mid-call** scoring for real-time coaching.

Keep training **offline** and serving **stateless** — the worker loads a versioned model artifact from the registry; no training in the request path.

---

## 7. Bot design feedback loop (auto-improvement)

Detection (Model C) is only useful if it closes the loop into **better bot design**:

1. **Aggregate** misbehavior classes per `prompt_version` / tool config over a rolling window.
2. **Recommend** the highest-leverage change (prompt rule vs. new tool vs. guardrail) with supporting example turns.
3. **Experiment**: ship the change behind a new `prompt_version`; the platform already stamps every result with `prompt_version`, so A/B comparison is a group-by.
4. **Verify** with an LLM-judge on a fixed evaluation set **before** production, and with online interaction-quality metrics **after**.
5. **Guardrail**: gate risky changes behind human approval; never auto-deploy prompt changes that touch compliance/PII behavior.

This is continuous evaluation (LLM-as-a-judge + golden set), the market-standard method to catch prompt regressions faster than a slow human-override feedback cycle.

---

## 8. Provider SLO monitoring & immediate alarms

**Goal:** guarantee STT/LLM (and storage/queue) providers serve requests **in time and in form**, and page operators the moment they don't.

### 8.1 What we measure

Per-stage latency is derived from `CallEvent` `STATUS_CHANGE` timestamps; call-level errors from `ERROR` events; provider-call latency should be logged explicitly around each `stt.transcribe` / `llm.complete_json` call.

| Metric | Definition | Why |
|--------|------------|-----|
| Stage latency p50/p95/p99 | Time between consecutive `STATUS_CHANGE` events | Detect slow providers before users feel it |
| Error rate | `ERROR` events / total, per `step` and per provider | "In form" — are responses valid? |
| Timeout / retry rate | Provider-call timeouts and self-repair retries | Early degradation signal |
| Queue wait / depth | Time in `PENDING`; broker backlog | Burst/backpressure health |
| Stuck jobs | State unchanged > threshold (e.g., `TRANSCRIBING` > 10 min) | Silent hangs |
| Schema-failure rate | LLM outputs that fail validation / hit `needs_review` fallback | Output *form* quality per `llm_model` |
| Throughput | Completions/min vs. expected (~7/min at 10k/day) | Capacity vs. demand |

### 8.2 Alerting strategy (best practices)

- **SLOs + error budgets**, not raw thresholds alone: define targets (e.g., p95 analyze latency < 30 s, success ≥ 99%), alert on **burn rate** to cut noise.
- **Multi-window** (fast + slow burn) to catch both spikes and slow drift.
- **Anomaly detection** on top of static thresholds: seasonal baselines (EWMA / Prophet-style) flag "unusual for this hour" even within nominal bounds.
- **Severity routing:** INFO → dashboard, WARN → Slack, CRITICAL → PagerDuty/on-call. The UI already has an SSE/polling channel — reuse it to surface a live **operator alarm banner**.
- **Actionable payloads:** every alarm links to the affected `call_id`s and the matching [`RUNBOOK.md`](./RUNBOOK.md) procedure.
- **Auto-mitigation hooks:** on sustained provider breach, trip a **circuit breaker** and **fail over** to the backup provider (the factory pattern makes STT/LLM swappable); DLQ + backoff for transient errors.

### 8.3 Alarm flow

```
 CallEvent / provider-call metrics
        │
        ▼
  Metrics collector ──► rolling SLO windows ──► rule + anomaly engine
                                                     │ breach
                        ┌────────────────────────────┼────────────────────────┐
                        ▼                             ▼                        ▼
                  Operator UI banner (SSE)     Slack (WARN)          PagerDuty (CRITICAL)
                        │
                        └► optional auto-action: circuit-break + provider failover
```

---

## 9. Evaluation & MLOps

**Offline (per model):** AUC-ROC and PR-AUC (classes are imbalanced — PR matters), **calibration** (reliability curve, Brier score) for the propensity model, macro-F1 for multi-label loss reasons, and agreement-with-human (Cohen's κ) for the LLM judge. Always report on the held-out golden set.

**Online:** decision uplift (win-rate lift when reps act on the score), override-rate trend (should fall as models improve), and alert precision/recall (are alarms actionable?).

**Drift & retraining:** monitor feature drift (PSI) and prediction drift; retrain on a cadence or on drift-trigger. Because every result carries `prompt_version` / `model`, regressions are attributable. Keep a **model registry** with versioned artifacts and one-click rollback — the same discipline Alembic gives the schema.

**Validate the judge:** an LLM judge is itself a model — periodically re-check its scores against fresh human labels so evaluation doesn't silently drift.

---

## 10. Data governance, privacy & ethics

- **PII first:** redact names, cards, phones (Presidio/NER) *before* features leave the pipeline; train on de-identified data. Consistent with the platform's PII stance.
- **No fully-automated adverse decisions:** predictions assist humans; they don't auto-reject customers or auto-deploy compliance-affecting prompt changes.
- **Fairness:** monitor for disparate error rates across language/segment; a model that only works on English calls is a bug.
- **Transparency:** ship SHAP drivers with every score so reps see *why*, and store provenance for audit.
- **Retention:** short retention on raw audio; keep de-identified features/labels for model history.

---

## 11. Phased roadmap

| Phase | Deliverable | Effort |
|-------|-------------|--------|
| **0 — Instrument** | `provider_metric` logging + SLO dashboard + alarms (Model D) | Small — pure ops win, no ML |
| **1 — Descriptive** | `call_features` store; loss-reason aggregates; override-rate reporting | Small |
| **2 — Predict** | Calibrated win-propensity (Model A) with SHAP; `prediction` table + endpoints | Medium |
| **3 — Bot QA loop** | LLM-judge Model C + prompt/tool recommendations wired to `prompt_version` A/B | Medium |
| **4 — Close the loop** | Online/mid-call scoring, drift monitoring, provider auto-failover | Larger |

Start with **Phase 0**: monitoring and alarms are the fastest, highest-certainty value and require no labels — they directly satisfy the "providers serve in time and raise immediate alarms" requirement while the ML data matures.

---

## 12. Best-practices summary

- **Hybrid over pure-LLM:** LLM for language, calibrated ML for probabilities, rules for guarantees.
- **Feature store** to kill train/serve skew; **model registry** for versioning and rollback.
- **Human-in-the-loop**: overrides are labels; humans approve consequential actions.
- **Continuous evaluation** (LLM-as-a-judge + golden set) to catch prompt/tool regressions early.
- **SLOs + error budgets + multi-window burn-rate alerts + anomaly detection**, with actionable, runbook-linked pages.
- **Circuit breaker + provider failover** via the existing factory abstraction.
- **Privacy by design**: redact before modeling; no automated adverse decisions; monitor fairness and drift.
