# Call Analyzer - Altur Take-home

Suite de transcripción de llamadas de ventas, análisis semántico automatizado y control de calidad (QA).

## 1. Overview & Screenshots
> 🚧 Se completa en la Fase 7.

## 2. Architecture
* **Arquitectura Orientada a Eventos / Desacoplada:** El pipeline asíncrono separa la ingesta (`POST /calls`), la transcripción (STT) y el análisis (LLM) usando una cola de trabajo (RQ) y workers dedicados.
* **Modos de Ejecución:**
  * **LOCAL_DEV:** SQLite para base de datos, RQ en modo burst (síncrono `fakeredis`), proveedores `FakeSTT` y `FakeLLM` deterministicos de fixtures y almacenamiento local en disco.
  * **LOCAL_DOCKER:** PostgreSQL, Redis, proveedores configurados y almacenamiento local.
  * **CLOUD:** PostgreSQL administrado, Redis administrado, S3 para almacenamiento y APIs reales de OpenAI.

## 3. Quickstart (LOCAL_DEV)
> 🚧 Se completa en la Fase 10.

## 4. Running with Docker
> 🚧 Se completa en la Fase 10.

## 5. Environment Variables
El proyecto utiliza un único contrato de variables de entorno configurado mediante Pydantic Settings.
* Véase [env.example](.env.example) para más detalles.
> 🚧 Se completa en la Fase 10.

## 6. API Reference
> 🚧 Se completa en la Fase 2 y 6.

## 7. Tagging Schema & Prompt Design
El analizador utiliza un esquema estructurado de 7 categorías de etiquetas de ventas.
* Véase [prompt_design.md](docs/prompt_design.md) para detalles del diseño del prompt y evaluación de calidad.

## 8. Testing
> 🚧 Se completa en la Fase 9.

## 9. Error Handling & State Machine
El sistema implementa una máquina de estados para realizar transiciones atómicas y garantizar la idempotencia de las colas.
* **Estados:** `PENDING ➔ TRANSCRIBING ➔ TRANSCRIBED ➔ ANALYZING ➔ DONE / FAILED`
> 🚧 Se completa en la Fase 8.

## 10. Deployment (Heroku)
> 🚧 Se completa en la Fase 10.

## 11. Assumptions & Trade-offs
> 🚧 Se completa en la Fase 10.

## 12. Roadmap (Mejoras Futuras)
> 🚧 Se completa en la Fase 10.
