# Prompt Design and Quality Evaluation Strategy

This document details the LLM prompt construction, structured sales tagging schema, and the continuous quality evaluation pipeline.

---

## 1. Prompt Design

The system prompts are version-controlled and structured to enforce strict JSON schemas. 

* **System Prompt Core:**
  * Defines the analyzer role (Expert Sales Call Auditor).
  * Directs the extraction of call summaries, participant names, sentiment scores, and buying signals.
  * Enforces the extraction of structured tags from a predefined, closed vocabulary.
  * Forbids preamble, markdown styling, or text outside the JSON output block.

---

## 2. Canonical Tagging Schema

The backend maps analysis results to a standardized schema:

| Tag Category | Description | Common Values |
| :--- | :--- | :--- |
| **`outcome`** | The direct result of the call | `follow_up_scheduled`, `demo_completed`, `lost`, `rejected`, `callback_requested` |
| **`next_step`** | Action item decided on the call | `demo_scheduled`, `proposal_sent`, `introductory_call`, `escalated_to_manager` |
| **`objection`** | Core hesitation raised by client | `price_objection`, `competitor_preference`, `timing_issue`, `no_objections_raised` |
| **`compliance_flag`** | Audit flag for quality assurance | `none`, `missing_disclaimer`, `aggressive_pitch`, `misleading_pricing` |

---

## 3. Continuous Quality Evaluation Pipeline

To guarantee the accuracy of AI classification tags over time and prevent regressions, the platform follows a structured evaluation lifecycle:

### A. The Gold Standard Dataset (Gold Set)
* A curated repository of 50–100 calls manually annotated by senior sales auditors.
* Serves as the ground truth benchmark for validation.

### B. Automated Regression Suite (LLM-as-a-Judge)
* Running on CI/CD pipelines, a secondary evaluation script inputs transcripts into the production analyzer.
* A judge LLM compares the output JSON schema and classifications against the Gold Set.
* Measures **Precision, Recall, and F1-Score** for each tag category. Any degradation below 95% accuracy blocks the deployment of new prompts.

```
                  ┌──────────────────────┐
                  │   New Prompt Draft   │
                  └──────────┬───────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │ Test Run on Gold Set Dataset │
              └──────────────┬───────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │    Judge LLM Evaluator       │
              └──────────────┬───────────────┘
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
   [Score >= 95% Accuracy]          [Score < 95% Accuracy]
      Deploy Prompt                    Block Deployment
```

### C. Feedback Loop (User Overrides)
* When a human auditor corrects a tag value on the UI, the correction is saved to the `call_tag_overrides` database table.
* The discrepancy is flagged, and the original call + correction is reviewed to update and retrain the system prompts.

### D. Tracking Semantic Drift
* Monitor the percentage distribution of extracted tags on production calls weekly.
* If a tag like `no_objections_raised` suddenly climbs from 35% to 80% without operational changes, the system flags potential prompt drift or model behavior changes.

### E. Prompt A/B Testing
* Deploy candidate prompts to a small subset (e.g., 10%) of production calls.
* Compare tag confidence values, override rates, and latency against the control prompt before rollouts.
