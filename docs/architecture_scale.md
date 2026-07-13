# Production Architecture and Scalability Strategy

This document outlines the system architecture choices, environment strategy, API bottlenecks, and scalability plan to support high-throughput operations.

---

## 1. Decoupled Processing: RQ vs. Celery

To ensure API endpoints remain highly responsive, file ingestion is completely decoupled from processing tasks using an asynchronous queue:

* **Why RQ (Redis Queue):**
  * **Simplicity:** RQ is lightweight and integrates natively with Python's existing function calls. It uses Redis as a backend and requires minimal setup.
  * **Dev-Prod Parity:** Allows running in synchronous burst mode using `fakeredis` in local development without needing a running Redis server instance.
* **Celery as a Production alternative:**
  * If the system grows to require complex task workflows (chords, chains, groups), multi-language workers, or advanced scheduling, Celery can replace RQ. It adds support for multiple message brokers (RabbitMQ, SQS) but introduces configuration complexity.

---

## 2. Execution Environments

The system is architected with a strict separation between local development and cloud production configurations:

```
┌────────────────────────────────────────────────────────────────────────┐
│                               LOCAL_DEV                                │
├───────────────────┬───────────────────┬────────────────────────────────┤
│ Storage           │ Database          │ Queue                          │
├───────────────────┼───────────────────┼────────────────────────────────┤
│ Local Disk        │ SQLite            │ Synchronous fakeredis          │
└───────────────────┴───────────────────┴────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│                            CLOUD PRODUCTION                            │
├───────────────────┬───────────────────┬────────────────────────────────┤
│ Storage           │ Database          │ Queue                          │
├───────────────────┼───────────────────┼────────────────────────────────┤
│ AWS S3 / GCS      │ PostgreSQL        │ Async Redis Queue (RQ/Celery)  │
└───────────────────┴───────────────────┴────────────────────────────────┘
```

### Local Development (`LOCAL_DEV`)
* **Database:** SQLite (`dev.db`).
* **Storage:** Local disk directory (`backend/data/audio/`).
* **Queue:** Synchronous RQ queue using `fakeredis` (burst execution inline).
* **Providers:** Fake deterministic implementations. Filenames match JSON fixtures to return static transcripts and analysis templates without API latency or credentials.

### Production (`CLOUD`)
* **Database:** Managed PostgreSQL (AWS RDS or GCP Cloud SQL) with migration deployment steps.
* **Storage:** AWS S3 or Google Cloud Storage. Serving uses presigned GET URLs with expiration bounds to restrict file exposure.
* **Queue:** Redis Cluster hosting an asynchronous queue with persistent RQ workers running on dedicated background nodes.
* **Providers:** Active external integrations (e.g., Deepgram/OpenAI Whisper for STT; GPT-4/Claude for LLM analysis).

---

## 3. Upstream API Bottlenecks & Mitigations

Relying on external Speech-to-Text and LLM providers introduces operational bottlenecks:

* **Latency:** Audio transcription and LLM inference can take several seconds to minutes.
  * *Mitigation:* Decoupling via queues ensures the client never blocks. The user receives `202 Accepted` and polls the status or listens to webhooks.
* **Rate Limits:** External API keys are subject to strict rate limits.
  * *Mitigation:* Workers implement exponential backoff retry algorithms when encountering HTTP `429` (Too Many Requests). Dead Letter Queues (DLQ) isolate consistently failing jobs.
* **Cost:** Analyzing large volumes of audio can grow expensive.
  * *Mitigation:* Audio compression prior to upload reduces file sizes. LLM requests use strict JSON response schemas to limit output token generation.

---

## 4. Scaling Responses

### Handling 10,000 calls per day
* 10,000 calls / 24 hours ≈ **7 calls per minute** on average.
* A single worker node running multiple worker threads can comfortably handle this load. SQLite can sustain this average write frequency, but migration to PostgreSQL is advised to support concurrent read/write isolation.

### Handling sudden bursts of 1,000 calls
* **Ingestion Layer:** The FastAPI endpoints write the file directly to storage (S3/GCS) and register a database record within milliseconds. 1,000 uploads are absorbed instantly without blocking the server thread pool.
* **Queue Layer:** The 1,000 transcription tasks accumulate safely in Redis.
* **Worker Autoscaling:** Background worker nodes are scaled dynamically using a Kubernetes Horizontal Pod Autoscaler (HPA) triggered by the size of the Redis queue.
* **Rate Limiting:** Workers process jobs at a steady pace to avoid hitting OpenAI/Deepgram rate limits, ensuring no jobs are dropped.
