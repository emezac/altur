# API Contract Findings — CALL-E and provider-agnostic ingestion

**Question that triggered this:** does CALL-E return raw audio and a full transcript
(so we can feed it straight into our pipeline), or only its own curated
`structured_result` + evidence (so we would be reselling a provider's self-assessment)?

**Method:** two independent sources — the official OpenAPI spec
(`docs.heycall-e.com/openapi/calle.openapi.yaml`, 62 KB) and a **real** completed call
we placed via `get_call_run` (28s, `COMPLETED`).

## What CALL-E actually returns

| Field | Present? | Evidence |
| --- | --- | --- |
| `transcript_turns` — `{offset_seconds, speaker∈{bot,user,unknown}, text}` per attempt | **Yes** | OpenAPI `CallTaskAttempt.transcript_turns` → `CallTranscriptTurn`; our real call returned the full turn-by-turn transcript |
| `structured_result` (validated against your `result_schema`) | Yes | `CallTask` |
| `task_completed`, `completion_confidence{score,label}`, `evidence[]` | Yes | `CallTask` |
| Terminal **webhook** carrying `transcript_turns` | Yes | `POST /calle/webhook` (`receiveWebhookEvent`) |
| `recording_url` / `audio_url` / any media URL | **No** | Absent from the entire OpenAPI **and** from our real payload |

**Conclusion — it is not "Scenario A vs B". It is "A without audio":**

- You **do** get a turn-level transcript (via GET and via webhook) → our `analyze_call`
  runs our own closed 7-category schema on **real content**, independently of CALL-E's
  self-assessment. STT (`transcribe_call`) becomes **optional** for this source.
- CALL-E **also** returns its own `structured_result` / `evidence` — the engine grading
  itself. We treat that as *another provider's opinion*, not ground truth.
- There is **no raw audio**. That is the one real limitation: no re-transcription with our
  own STT, no voice/acoustic analysis, no audio-level evidence for compliance.

## Why this strengthens the positioning

Because CALL-E hands over the **transcript** (not just its summary), the
independent-auditor play is technically possible and defensible:

> We analyze any call independently and auditably — regardless of which engine placed
> it — with a closed schema, human-override traceability, and drift monitoring. That is
> exactly what the engine that made the call cannot credibly provide about itself.

The absence of audio also argues *for* being provider-agnostic: sources that **do**
expose audio (Twilio, Aircall, a recordings bucket) fill the gap CALL-E leaves. The
analyzer should accept both a transcript and an audio URL, from any source.

## Design decision: one generic ingestion endpoint

Ingestion is modeled as a provider-agnostic webhook, **not** a CALL-E-specific
integration. CALL-E is the first connector, not the only input.

`POST /api/v1/calls/webhook` — `app/api/calls.py`, schema `app/schemas/webhook.py`,
service `app/services/ingest_service.py`:

```jsonc
{
  "source": "calle",                 // twilio | aircall | manual | …
  "language": "es",                  // optional; else detected
  "transcript_turns": [              // transcript-first (CALL-E): STT skipped
    { "speaker": "bot",  "text": "…", "offset_seconds": 0 },
    { "speaker": "user", "text": "…", "offset_seconds": 6 }
  ],
  // "audio_url": "https://…/rec.wav" // audio-first (Twilio): runs transcribe_call
  "owner_id": "tenant-42",           // multi-tenancy / API-key auth hook
  "metadata": { "external_call_id": "…" }
}
```

- **transcript-first** → persist the `Transcript`, normalize provider speaker labels to
  `agent`/`customer`, jump straight to `TRANSCRIBED`, enqueue `analyze_call`.
- **audio-first** → register the call against the audio URL, enqueue `transcribe_call`.
  *Open seam:* the STT adapter must fetch a remote URL — the one piece left to build for
  audio-first sources.
- The ingest `source` + caller `metadata` are recorded as a `WEBHOOK_INGEST` event
  (audited, not silently trusted). `owner_id` is the multi-tenancy / SaaS-auth hook.

Covered by `tests/integration/test_webhook_ingest.py` (transcript-first, audio-first,
and the "one input required" guard).

## Practical guidance carried forward

1. **Confirmed:** transcript yes, recording no — do not design anything that assumes
   access to CALL-E audio.
2. **Ingest is generic**, per the endpoint above — CALL-E is a connector.
3. **SaaS packaging:** `owner_id` (already on `Call`) is the seam for API-key auth and
   per-tenant pricing per analyzed call; it is a starting point, not yet built out.
4. **Validate cheaply first:** both this analyzer and the CALL-E CLI have `fake`/test
   modes; contract-test the integration before spending on real calls whose pricing is
   not final.
