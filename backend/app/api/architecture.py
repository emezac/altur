"""
Architecture & scaling reference endpoint.

Exposes a machine-readable description of the application's modular components
and the production scaling strategy required to meet the challenge's demand
targets (30-minute audio, immediate upload acknowledgement, 1,000-recording
bursts, and 10,000 calls/day). The frontend renders this into a documentation
page alongside a hand-authored SVG architecture diagram.

The document is a static, hand-curated constant: it is the single source of
truth for the "how it works / how it scales" narrative and is intentionally
decoupled from runtime state so it can be fetched cheaply and cached.
"""
from fastapi import APIRouter

router = APIRouter()

ARCHITECTURE = {
    "app": "Call Analyzer",
    "summary": (
        "A decoupled, status-driven pipeline that ingests a sales call, transcribes "
        "it with a speech-to-text model, and analyzes the transcript with an LLM to "
        "produce a summary, sentiment, purchase intent, and a structured sales-tagging "
        "schema. The upload endpoint returns immediately (202 Accepted) and all heavy "
        "work runs asynchronously so the UI never blocks."
    ),
    "constraints": [
        "Calls can be up to 30 minutes long.",
        "The upload endpoint must return immediately.",
        "Users may submit ~1,000 recordings in a short burst.",
        "The system must scale to 10,000 calls/day.",
    ],
    "principles": [
        "Separation of concerns: thin API, fat workers, swappable providers.",
        "Provider abstraction via factories (fake / OpenAI / Qwen) — no vendor lock-in.",
        "Idempotent, at-least-once-safe processing guarded by an atomic state machine.",
        "Everything observable: structured logs, request IDs, and an immutable audit trail.",
    ],
    "layers": [
        {
            "id": "client",
            "title": "Web Client (SPA)",
            "tech": "Vanilla JS + HTML/CSS",
            "responsibility": (
                "Drag-and-drop upload, live status polling, transcript playback synced "
                "to audio, insight dashboard, and human tag overrides."
            ),
            "best_practices": [
                "Non-blocking upload with progress + optimistic UI",
                "Lightweight polling of a dedicated status endpoint",
                "Graceful states for PENDING / PROCESSING / FAILED",
            ],
        },
        {
            "id": "api",
            "title": "Ingestion & API",
            "tech": "FastAPI",
            "responsibility": (
                "Validates uploads, persists metadata, enqueues background work, and "
                "serves list/detail/status/export endpoints."
            ),
            "best_practices": [
                "Return 202 Accepted immediately; never process inline in the request",
                "Validate magic-byte signature + size before touching storage",
                "Pre-flight queue health check so calls are never accepted without a worker",
                "Versioned API surface (/api/v1) and typed Pydantic schemas",
            ],
        },
        {
            "id": "storage",
            "title": "Object Storage",
            "tech": "Local disk (dev) → S3 / GCS (prod)",
            "responsibility": "Durable storage of the raw audio, abstracted behind a storage interface.",
            "best_practices": [
                "Pluggable backend via a storage factory (local / S3)",
                "In prod: presigned-URL direct upload to keep the API stateless & light",
                "Private buckets with lifecycle rules (expire raw audio, keep redacted transcript)",
            ],
        },
        {
            "id": "queue",
            "title": "Message Broker & Queue",
            "tech": "RQ + fakeredis (dev) → Redis / RabbitMQ / Kafka (prod)",
            "responsibility": "Buffers and orchestrates async jobs, absorbing bursts safely.",
            "best_practices": [
                "Decouple ingestion from processing so bursts queue instead of dropping",
                "At-least-once delivery paired with idempotent consumers",
                "Dead-letter queue (DLQ) for poison messages and retries with backoff",
            ],
        },
        {
            "id": "stt",
            "title": "STT Workers",
            "tech": "Provider factory: fake / OpenAI Whisper (Deepgram / AssemblyAI ready)",
            "responsibility": "Transcribe audio into diarized turns with timestamps and language.",
            "best_practices": [
                "Swappable provider behind a single STTProvider interface",
                "Long-audio strategy: VAD-aware chunking + dual-channel diarization",
                "Persist transcript before signalling the next stage",
            ],
        },
        {
            "id": "llm",
            "title": "LLM Analysis Workers",
            "tech": "Provider factory: fake / OpenAI (prod) / Qwen (dev)",
            "responsibility": (
                "Turn the transcript into a summary, sentiment, intent, insights, and a "
                "validated sales-tagging schema."
            ),
            "best_practices": [
                "Schema-bound prompt with allowed enum values derived from the validation layer",
                "Structured JSON output with a self-repair retry, then a safe needs-review fallback",
                "Provider + model + prompt_version stored on every result for evaluation",
            ],
        },
        {
            "id": "state",
            "title": "State Machine & Idempotency",
            "tech": "Atomic conditional UPDATEs",
            "responsibility": "Guards every PENDING→…→COMPLETED transition against duplicate delivery.",
            "best_practices": [
                "UPDATE ... WHERE status = :expected (optimistic concurrency)",
                "Duplicate job deliveries are discarded — no double STT/LLM cost",
                "Error boundary transitions to FAILED and records the cause",
            ],
        },
        {
            "id": "db",
            "title": "Persistence",
            "tech": "SQLAlchemy + Alembic — SQLite (dev) → PostgreSQL (prod)",
            "responsibility": "Stores calls, transcripts, summaries, EAV tags, and the audit trail.",
            "best_practices": [
                "Relational core + JSONB for flexible insights/tagging (Postgres)",
                "Migrations under version control (Alembic)",
                "Full-text search (tsvector + GIN) and read replicas for scale",
            ],
        },
        {
            "id": "observability",
            "title": "Observability & Audit",
            "tech": "Structured logging + request IDs + CallEvent audit log",
            "responsibility": "Traceability of every state change and error for debugging and compliance.",
            "best_practices": [
                "Correlation IDs propagated per request",
                "Immutable, append-only audit events per call",
                "Model-quality signals (override rate, confidence) captured for monitoring",
            ],
        },
    ],
    "pipeline": [
        {"step": "Upload", "state": "PENDING", "detail": "Client uploads audio; API validates, stores, persists metadata, returns 202."},
        {"step": "Enqueue", "state": "PENDING", "detail": "transcribe_call job is placed on the queue."},
        {"step": "Transcribe", "state": "TRANSCRIBING → TRANSCRIBED", "detail": "STT worker produces diarized turns; transcript persisted; analysis enqueued."},
        {"step": "Analyze", "state": "ANALYZING → COMPLETED", "detail": "LLM worker produces summary + tags; validated and persisted."},
        {"step": "Notify", "state": "COMPLETED", "detail": "UI observes completion via status polling (SSE/WebSockets in prod)."},
    ],
    "scaling": {
        "dev": (
            "Single process. REDIS_URL empty → RQ runs inline with fakeredis, SQLite, and "
            "local disk. The whole pipeline executes in-request for zero-dependency testing."
        ),
        "production": (
            "Horizontally scalable, event-driven services on containers (Cloud Run / ECS / "
            "Kubernetes). At ~10k calls/day (~7/min average, with bursts) the API stays thin "
            "and stateless while worker pools scale on queue depth."
        ),
        "strategy": [
            {"title": "Direct-to-storage uploads", "detail": "Presigned URLs let clients upload 30-min files straight to S3/GCS, keeping the API off the data path."},
            {"title": "Autoscaling workers", "detail": "Scale STT/LLM worker pools on queue depth (KEDA / Cloud Run concurrency), independently per stage."},
            {"title": "Backpressure via the broker", "detail": "A 1,000-file burst queues safely instead of overwhelming providers or the DB."},
            {"title": "Managed Postgres + caching", "detail": "Connection pooling, read replicas, and Redis caching for hot list/analytics reads."},
            {"title": "Resilient jobs", "detail": "Idempotent consumers, retries with exponential backoff, and a DLQ for corrupt audio."},
        ],
        "bottlenecks": [
            {"name": "External API rate limits (STT/LLM RPM & TPM)", "mitigation": "Queue-based throttling, per-provider concurrency caps, and multi-provider failover."},
            {"name": "API bandwidth/memory on large uploads", "mitigation": "Presigned direct-to-storage uploads remove big files from the API entirely."},
            {"name": "Database contention at scale", "mitigation": "Read replicas, JSONB + GIN indexes, and Redis read-through cache."},
            {"name": "Long single-file latency (30 min)", "mitigation": "VAD-aware chunking + parallel channel transcription, reassembled by timestamp."},
        ],
        "pii": [
            "Redact PII (names, cards, phones) before persisting or sending to external LLMs — Presidio/NER at the edge.",
            "Encrypt Postgres at rest (AES-256) and use private buckets with strict lifecycle policies.",
            "Delete raw audio on a short retention window; keep only the de-identified transcript.",
            "Scope credentials least-privilege; keep secrets out of source control.",
        ],
    },
}


@router.get("/architecture")
def get_architecture():
    """Returns the modular architecture description and production scaling strategy."""
    return ARCHITECTURE
