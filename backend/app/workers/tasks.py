import json
import logging
from app.core.db import SessionLocal
from app.models.call import Call
from app.models.transcript import Transcript
from app.models.summary import Summary
from app.models.tag import CallTag
from app.models.event import CallEvent
from app.services.stt.factory import get_stt_provider
from app.services.llm.factory import get_llm_provider
from app.workers.queue import get_queue

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
    """
    logger.info(f"Starting transcribe_call task for call_id: {call_id}")
    db = SessionLocal()
    try:
        call = db.query(Call).filter(Call.id == call_id).first()
        if not call:
            logger.error(f"Call {call_id} not found in database.")
            return

        # Ensure call is in a correct starting state (supports retries from FAILED)
        if call.status not in ("PENDING", "FAILED"):
            logger.warning(f"Call {call_id} is in status '{call.status}', skipping transcription.")
            return

        # 1. Transition call status to TRANSCRIBING
        old_status = call.status
        call.status = "TRANSCRIBING"
        db.add(CallEvent(
            call_id=call.id,
            event_type="STATUS_CHANGE",
            payload={"from_status": old_status, "to_status": "TRANSCRIBING"}
        ))
        db.commit()

        # 2. Transcribe audio file
        stt = get_stt_provider()
        result = stt.transcribe(call.storage_path)

        # 3. Persist transcript record
        raw_text = " ".join(turn.text for turn in result.turns)
        turns_list = [turn.model_dump() for turn in result.turns]

        db_transcript = Transcript(
            call_id=call.id,
            language=result.language,
            raw_text=raw_text,
            turns=turns_list,
            stt_confidence=result.stt_confidence,
            stt_provider=result.provider,
            stt_model=result.model
        )
        db.add(db_transcript)

        # 4. Transition call status to TRANSCRIBED
        call.status = "TRANSCRIBED"
        db.add(CallEvent(
            call_id=call.id,
            event_type="STATUS_CHANGE",
            payload={"from_status": "TRANSCRIBING", "to_status": "TRANSCRIBED"}
        ))
        db.commit()
        logger.info(f"Call {call_id} successfully transcribed and set to TRANSCRIBED.")

        # 5. Enqueue analysis task
        queue = get_queue()
        queue.enqueue(analyze_call, call_id)
        logger.info(f"Enqueued analyze_call task for call_id: {call_id}")

    except Exception as e:
        logger.exception(f"Error during transcribe_call task for call_id {call_id}: {e}")
        if _TESTING:
            db.expire_all()
        else:
            db.rollback()


        # Error Boundary: Transition status to FAILED and write error details to events log
        try:
            # Re-fetch call in case transaction state is discarded
            call = db.query(Call).filter(Call.id == call_id).first()
            if call:
                old_status = call.status
                call.status = "FAILED"
                db.add(CallEvent(
                    call_id=call.id,
                    event_type="STATUS_CHANGE",
                    payload={"from_status": old_status, "to_status": "FAILED"}
                ))
                db.add(CallEvent(
                    call_id=call.id,
                    event_type="ERROR",
                    payload={"step": "TRANSCRIBE", "error": str(e)}
                ))
                db.commit()
                logger.info(f"Call {call_id} status updated to FAILED due to exception.")
        except Exception as status_err:
            logger.error(f"Failed to record FAILED status for call {call_id}: {status_err}")
    finally:
        if not _TESTING:
            db.close()

def analyze_call(call_id: str) -> None:
    """
    Retrieves Call and associated Transcript, requests analysis via LLM provider,
    persists Summary and CallTag models, logs events, and transitions status to COMPLETED.
    """
    logger.info(f"Starting analyze_call task for call_id: {call_id}")
    db = SessionLocal()
    try:
        call = db.query(Call).filter(Call.id == call_id).first()
        if not call:
            logger.error(f"Call {call_id} not found in database.")
            return

        # Ensure call is in a correct starting state
        if call.status not in ("TRANSCRIBED", "FAILED"):
            logger.warning(f"Call {call_id} is in status '{call.status}', skipping analysis.")
            return

        transcript = db.query(Transcript).filter(Transcript.call_id == call_id).first()
        if not transcript:
            logger.error(f"Transcript record for call {call_id} not found.")
            call.status = "FAILED"
            db.add(CallEvent(
                call_id=call.id,
                event_type="ERROR",
                payload={"step": "ANALYZE", "error": "Transcript record not found"}
            ))
            db.commit()
            return

        # 1. Transition call status to ANALYZING
        old_status = call.status
        call.status = "ANALYZING"
        db.add(CallEvent(
            call_id=call.id,
            event_type="STATUS_CHANGE",
            payload={"from_status": old_status, "to_status": "ANALYZING"}
        ))
        db.commit()

        # 2. Run LLM Analysis
        system_prompt = (
            "You are an expert sales call analyzer. Parse the transcription and extract structured "
            "insights including executive summary, key points, sentiment, purchase intent, insights "
            "(buying signals, risks, inconsistencies, tone notes) and sales tags (outcome, next step, "
            "objections, compliance, product interest). Your response must be JSON only."
        )
        llm = get_llm_provider()
        raw_analysis = llm.complete_json(system_prompt, transcript.raw_text)

        # 3. Parse JSON response and save results
        parsed = json.loads(raw_analysis)
        summary_data = parsed["summary"]
        tags_data = parsed["tags"]

        # Build a rich insights blob that includes the executive summary and sentiment scores
        insights_blob = {
            "executive_summary": summary_data["executive_summary"],
            "sentiment": summary_data["sentiment"],
            "sentiment_score": summary_data["sentiment_score"],
            "purchase_intent": summary_data["purchase_intent"],
            "intent_score": summary_data["intent_score"],
            **summary_data["insights"]
        }

        db_summary = Summary(
            call_id=call.id,
            summary_text=summary_data["executive_summary"],
            key_points=summary_data["key_points"],
            insights=insights_blob,
            llm_provider="fake",
            llm_model="fake-llm-1",
            prompt_version="v1"
        )
        db.add(db_summary)

        # Persist tags as individual EAV rows (one row per tag category)
        tag_rows = [
            CallTag(call_id=call.id, tag_category="outcome",
                    tag_value=tags_data["outcome"],
                    confidence=tags_data["outcome_confidence"]),
            CallTag(call_id=call.id, tag_category="next_step",
                    tag_value=tags_data["next_step"],
                    confidence=tags_data["next_step_confidence"]),
            CallTag(call_id=call.id, tag_category="objection",
                    tag_value=tags_data["objection"],
                    confidence=tags_data["objection_confidence"]),
            CallTag(call_id=call.id, tag_category="compliance_flag",
                    tag_value=tags_data["compliance_flag"],
                    confidence=1.0),
        ]
        for row in tag_rows:
            db.add(row)


        # 4. Transition call status to COMPLETED
        call.status = "COMPLETED"
        db.add(CallEvent(
            call_id=call.id,
            event_type="STATUS_CHANGE",
            payload={"from_status": "ANALYZING", "to_status": "COMPLETED"}
        ))
        db.commit()
        logger.info(f"Call {call_id} successfully analyzed and set to COMPLETED.")

    except Exception as e:
        logger.exception(f"Error during analyze_call task for call_id {call_id}: {e}")
        if _TESTING:
            db.expire_all()
        else:
            db.rollback()


        # Error Boundary: Transition status to FAILED and write error details to events log
        try:
            call = db.query(Call).filter(Call.id == call_id).first()
            if call:
                old_status = call.status
                call.status = "FAILED"
                db.add(CallEvent(
                    call_id=call.id,
                    event_type="STATUS_CHANGE",
                    payload={"from_status": old_status, "to_status": "FAILED"}
                ))
                db.add(CallEvent(
                    call_id=call.id,
                    event_type="ERROR",
                    payload={"step": "ANALYZE", "error": str(e)}
                ))
                db.commit()
                logger.info(f"Call {call_id} status updated to FAILED due to exception.")
        except Exception as status_err:
            logger.error(f"Failed to record FAILED status for call {call_id}: {status_err}")
    finally:
        if not _TESTING:
            db.close()

