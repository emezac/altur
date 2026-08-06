import json
import logging
import os
from app.core.db import SessionLocal
from app.models.call import Call
from app.models.transcript import Transcript
from app.models.summary import Summary
from app.models.tag import CallTag
from app.models.event import CallEvent
from app.services.stt.factory import get_stt_provider
from app.services.remote_audio import is_remote_url, fetch_to_tempfile
from app.services.llm.factory import get_llm_provider
from app.services.state_machine import transition
from app.workers.queue import get_queue
from app.core.config import settings
from app.schemas.tag_schema import TagCategory, ALLOWED_VALUES


def _build_analysis_system_prompt() -> str:
    """
    Builds the analysis system prompt with an explicit output schema. The allowed
    enum values are derived from tag_schema.ALLOWED_VALUES so the prompt never
    drifts from the validation layer. Real LLMs (OpenAI, Qwen) need the exact
    nested envelope spelled out — the fake fixtures happened to match it, which
    hid the requirement.
    """
    def opts(category: TagCategory) -> str:
        return " | ".join(sorted(ALLOWED_VALUES[category]))

    return (
        "You are an expert sales-call analyzer. Read the transcript and return your "
        "analysis.\n"
        "Return ONLY a single JSON object (no markdown, no code fences) that matches "
        "EXACTLY this schema:\n"
        "{\n"
        '  "summary": {\n'
        '    "executive_summary": string,\n'
        '    "key_points": [string, ...],\n'
        f'    "sentiment": one of [{opts(TagCategory.SENTIMENT)}],\n'
        '    "sentiment_score": number between 0 and 1,\n'
        f'    "purchase_intent": one of [{opts(TagCategory.INTENT_LEVEL)}],\n'
        '    "intent_score": number between 0 and 1,\n'
        '    "insights": {\n'
        '      "buying_signals": [string, ...],\n'
        '      "risks": [string, ...],\n'
        '      "inconsistencies": [string, ...],\n'
        '      "tone_notes": string\n'
        "    }\n"
        "  },\n"
        '  "tags": {\n'
        f'    "outcome": one of [{opts(TagCategory.OUTCOME)}],\n'
        '    "outcome_confidence": number between 0 and 1,\n'
        f'    "next_step": one of [{opts(TagCategory.NEXT_STEP)}],\n'
        '    "next_step_confidence": number between 0 and 1,\n'
        f'    "objection": one of [{opts(TagCategory.OBJECTION_TYPE)}],\n'
        '    "objection_confidence": number between 0 and 1,\n'
        f'    "compliance_flag": one of [{opts(TagCategory.COMPLIANCE_FLAG)}],\n'
        '    "product_interest": [string, ...]\n'
        "  }\n"
        "}\n"
        'The "summary" and "tags" root keys are REQUIRED. Use only the allowed enum '
        "values verbatim. Detect the transcript language and write the summary in that "
        "language. Do not silently correct numeric inconsistencies — record them under "
        '"inconsistencies" instead.'
    )

# Set this to True in tests to prevent tasks from closing an injected session
_TESTING = False

logger = logging.getLogger(__name__)

def ping() -> str:
    """
    Simple task to test queue functionality.
    """
    logger.info("Executing ping task.")
    return "pong"

def transcribe_call(call_id: str) -> None:
    """
    Retrieves the audio from local/cloud storage, runs transcription via STT provider,
    persists Transcript record, logs events, and enqueues analyze_call.

    Idempotency: uses state_machine.transition() (atomic conditional UPDATE) to guard
    the PENDING -> TRANSCRIBING transition. If the row is no longer in PENDING state
    (e.g. a duplicate job delivery), the transition returns False and the task exits
    immediately -- no extra STT call, no double cost.
    """
    logger.info(f"[call_id={call_id}] Starting transcribe_call task")
    db = SessionLocal()
    try:
        call = db.query(Call).filter(Call.id == call_id).first()
        if not call:
            logger.error(f"[call_id={call_id}] Call not found in database -- aborting")
            return

        # Guard: only PENDING (or FAILED for retry) is a valid starting state
        if call.status not in ("PENDING", "FAILED"):
            logger.warning(
                f"[call_id={call_id}] Status is '{call.status}' -- not a valid starting state, "
                "discarding duplicate job delivery"
            )
            return

        # Atomic transition: if another worker already claimed this call, exit cleanly
        if not transition(db, call_id, call.status, "TRANSCRIBING"):
            logger.warning(
                f"[call_id={call_id}] Transition to TRANSCRIBING rejected -- "
                "duplicate job delivery, discarding"
            )
            return

        # Transcribe audio file. Audio-first webhook ingestion stores an HTTPS URL
        # in storage_path; fetch it to a local temp file (SSRF-guarded) first, then
        # always clean it up. Local/S3 paths pass through unchanged.
        stt = get_stt_provider()
        local_audio = None
        try:
            audio_ref = call.storage_path
            if is_remote_url(audio_ref):
                local_audio = fetch_to_tempfile(audio_ref)
                audio_ref = local_audio
            result = stt.transcribe(audio_ref)
        finally:
            if local_audio and os.path.exists(local_audio):
                os.unlink(local_audio)

        # Persist transcript record
        raw_text = " ".join(turn.text for turn in result.turns)
        turns_list = [turn.model_dump() for turn in result.turns]

        db_transcript = Transcript(
            call_id=call_id,
            language=result.language,
            raw_text=raw_text,
            turns=turns_list,
            stt_confidence=result.stt_confidence,
            stt_provider=result.provider,
            stt_model=result.model,
        )
        db.add(db_transcript)
        db.flush()

        # Atomic transition to TRANSCRIBED
        if not transition(db, call_id, "TRANSCRIBING", "TRANSCRIBED"):
            logger.error(
                f"[call_id={call_id}] Could not transition TRANSCRIBING->TRANSCRIBED "
                "(concurrent modification). Transcript saved but status inconsistent."
            )
            return

        logger.info(f"[call_id={call_id}] Transcription complete -- enqueuing analysis")

        # Enqueue analysis task
        queue = get_queue()
        queue.enqueue(analyze_call, call_id)

    except Exception as e:
        logger.exception(f"[call_id={call_id}] Unhandled error in transcribe_call: {e}")
        if _TESTING:
            db.expire_all()
        else:
            db.rollback()

        # Error boundary: atomically move to FAILED from whatever current state
        try:
            call = db.query(Call).filter(Call.id == call_id).first()
            if call and call.status not in ("COMPLETED", "FAILED"):
                transition(db, call_id, call.status, "FAILED")
            # Always record the error event regardless of whether transition succeeded
            if call:
                db.add(CallEvent(
                    call_id=call_id,
                    event_type="ERROR",
                    payload={"step": "TRANSCRIBE", "error": str(e)},
                ))
                db.commit()
                logger.info(f"[call_id={call_id}] Recorded ERROR event after transcription failure")
        except Exception as inner_err:
            logger.error(
                f"[call_id={call_id}] Failed to record FAILED status after transcription error: {inner_err}"
            )
    finally:
        if not _TESTING:
            db.close()

def analyze_call(call_id: str) -> None:
    """
    Retrieves Call and associated Transcript, requests analysis via LLM provider,
    persists Summary and CallTag models, logs events, and transitions status to COMPLETED.

    Idempotency: uses state_machine.transition() for TRANSCRIBED -> ANALYZING so that
    a redelivered job is discarded without re-invoking the LLM.
    """
    logger.info(f"[call_id={call_id}] Starting analyze_call task")
    db = SessionLocal()
    try:
        call = db.query(Call).filter(Call.id == call_id).first()
        if not call:
            logger.error(f"[call_id={call_id}] Call not found in database -- aborting")
            return

        # Guard: only TRANSCRIBED (or FAILED for retry) is a valid starting state
        if call.status not in ("TRANSCRIBED", "FAILED"):
            logger.warning(
                f"[call_id={call_id}] Status is '{call.status}' -- not a valid starting state, "
                "discarding duplicate job delivery"
            )
            return

        transcript = db.query(Transcript).filter(Transcript.call_id == call_id).first()
        if not transcript:
            logger.error(f"[call_id={call_id}] Transcript not found -- transitioning to FAILED")
            transition(db, call_id, call.status, "FAILED")
            db.add(CallEvent(
                call_id=call_id,
                event_type="ERROR",
                payload={"step": "ANALYZE", "error": "Transcript record not found"},
            ))
            db.commit()
            return

        # Atomic transition: discard duplicate job delivery
        if not transition(db, call_id, call.status, "ANALYZING"):
            logger.warning(
                f"[call_id={call_id}] Transition to ANALYZING rejected -- "
                "duplicate job delivery, discarding"
            )
            return

        # LLM analysis with self-repair (1 retry)
        system_prompt = _build_analysis_system_prompt()
        llm = get_llm_provider()
        
        parsed = None
        raw_analysis = ""
        try:
            raw_analysis = llm.complete_json(system_prompt, transcript.raw_text)
        except Exception as provider_err:
            # Infrastructure/provider error -- raise to transition to FAILED
            raise provider_err

        try:
            parsed = json.loads(raw_analysis)
            if "summary" not in parsed or "tags" not in parsed:
                raise ValueError("Missing summary or tags root key")
        except (json.JSONDecodeError, ValueError, KeyError) as first_err:
            logger.warning(
                f"[call_id={call_id}] First LLM analysis parse failed: {first_err}. "
                "Attempting self-repair retry."
            )
            try:
                repair_prompt = system_prompt + " YOUR PREVIOUS ATTEMPT FAILED TO PARSE AS VALID JSON. YOU MUST RETURN VALID JSON ONLY."
                raw_analysis = llm.complete_json(repair_prompt, transcript.raw_text)
            except Exception as provider_err:
                raise provider_err

            try:
                parsed = json.loads(raw_analysis)
                if "summary" not in parsed or "tags" not in parsed:
                    raise ValueError("Missing summary or tags root key in self-repair attempt")
            except (json.JSONDecodeError, ValueError, KeyError) as second_err:
                logger.error(
                    f"[call_id={call_id}] LLM analysis self-repair retry failed: {second_err}. "
                    "Degrading to needs_review fallback."
                )
                parsed = {
                    "summary": {
                        "executive_summary": f"Review Required. Raw analysis output failed to parse as valid JSON. Raw content: {raw_analysis}",
                        "key_points": ["Manual review required."],
                        "sentiment": "neutral",
                        "sentiment_score": 0.5,
                        "purchase_intent": "medium",
                        "intent_score": 0.5,
                        "insights": {
                            "buying_signals": [],
                            "risks": [],
                            "inconsistencies": [],
                            "tone_notes": "JSON parsing failed after self-repair.",
                            "needs_review": True
                        }
                    },
                    "tags": {
                        "outcome": "no_decision",
                        "outcome_confidence": 0.0,
                        "next_step": "call_again_follow_up",
                        "next_step_confidence": 0.0,
                        "objection": "no_objections_raised",
                        "objection_confidence": 0.0,
                        "compliance_flag": "none",
                        "product_interest": []
                    }
                }

        summary_data = parsed["summary"]
        tags_data = parsed["tags"]

        insights_blob = {
            "executive_summary": summary_data["executive_summary"],
            "sentiment": summary_data["sentiment"],
            "sentiment_score": summary_data["sentiment_score"],
            "purchase_intent": summary_data["purchase_intent"],
            "intent_score": summary_data["intent_score"],
            **summary_data["insights"],
        }

        llm_provider = (settings.LLM_PROVIDER or "fake").lower()
        llm_model = {
            "openai": settings.OPENAI_LLM_MODEL,
            "qwen": settings.QWEN_MODEL,
        }.get(llm_provider, "fake-llm-1")

        db_summary = Summary(
            call_id=call_id,
            summary_text=summary_data["executive_summary"],
            key_points=summary_data["key_points"],
            insights=insights_blob,
            llm_provider=llm_provider,
            llm_model=llm_model,
            prompt_version="v1",
        )
        db.add(db_summary)

        tag_rows = [
            CallTag(call_id=call_id, tag_category="outcome",
                    tag_value=tags_data["outcome"],
                    confidence=tags_data["outcome_confidence"]),
            CallTag(call_id=call_id, tag_category="next_step",
                    tag_value=tags_data["next_step"],
                    confidence=tags_data["next_step_confidence"]),
            CallTag(call_id=call_id, tag_category="objection",
                    tag_value=tags_data["objection"],
                    confidence=tags_data["objection_confidence"]),
            CallTag(call_id=call_id, tag_category="compliance_flag",
                    tag_value=tags_data["compliance_flag"],
                    confidence=1.0),
        ]
        for row in tag_rows:
            db.add(row)
        db.flush()

        # Atomic transition to COMPLETED
        if not transition(db, call_id, "ANALYZING", "COMPLETED"):
            logger.error(
                f"[call_id={call_id}] Could not transition ANALYZING->COMPLETED "
                "(concurrent modification). Data saved but status inconsistent."
            )
            return

        logger.info(f"[call_id={call_id}] Analysis complete -- call is COMPLETED")

    except Exception as e:
        logger.exception(f"[call_id={call_id}] Unhandled error in analyze_call: {e}")
        if _TESTING:
            db.expire_all()
        else:
            db.rollback()

        # Error boundary: atomically move to FAILED
        try:
            call = db.query(Call).filter(Call.id == call_id).first()
            if call and call.status not in ("COMPLETED", "FAILED"):
                transition(db, call_id, call.status, "FAILED")
            if call:
                db.add(CallEvent(
                    call_id=call_id,
                    event_type="ERROR",
                    payload={"step": "ANALYZE", "error": str(e)},
                ))
                db.commit()
                logger.info(f"[call_id={call_id}] Recorded ERROR event after analysis failure")
        except Exception as inner_err:
            logger.error(
                f"[call_id={call_id}] Failed to record FAILED status after analysis error: {inner_err}"
            )
    finally:
        if not _TESTING:
            db.close()
