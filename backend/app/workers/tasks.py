import logging
from app.core.db import SessionLocal
from app.models.call import Call
from app.models.event import CallEvent

logger = logging.getLogger(__name__)

def ping() -> str:
    """
    Simple task to test queue functionality.
    """
    logger.info("Executing ping task.")
    return "pong"

def transcribe_call(call_id: str) -> None:
    """
    Baseline task for transcribing a call. In this phase, it serves
    as a stub that transitions the call status to TRANSCRIBING.
    """
    logger.info(f"Executing transcribe_call task for call_id: {call_id}")
    db = SessionLocal()
    try:
        call = db.query(Call).filter(Call.id == call_id).first()
        if not call:
            logger.error(f"Call {call_id} not found in database.")
            return

        old_status = call.status
        call.status = "TRANSCRIBING"

        # Log status change event
        event = CallEvent(
            call_id=call.id,
            event_type="STATUS_CHANGE",
            payload={"from_status": old_status, "to_status": "TRANSCRIBING"}
        )
        db.add(event)
        db.commit()
        logger.info(f"Call {call_id} successfully updated from status '{old_status}' to 'TRANSCRIBING'.")
        
    except Exception as e:
        logger.exception(f"Error during transcribe_call task for call_id {call_id}: {e}")
        db.rollback()
    finally:
        db.close()
