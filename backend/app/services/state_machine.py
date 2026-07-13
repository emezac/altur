import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.call import Call
from app.models.event import CallEvent

logger = logging.getLogger(__name__)

def transition(db: Session, call_id: str, from_status: str, to_status: str) -> bool:
    """
    Atomically updates calls SET status=:to_status, updated_at=now() 
    WHERE id=:call_id AND status=:from_status.
    
    Returns True if 1 row was updated. If False, indicates a state conflict 
    or duplicate job execution (discard job).
    
    If successful, registers a STATUS_CHANGE event in call_events.
    """
    now = datetime.now(timezone.utc)
    rows = db.query(Call).filter(
        Call.id == call_id,
        Call.status == from_status
    ).update(
        {Call.status: to_status, Call.updated_at: now},
        synchronize_session=False
    )
    
    if rows == 1:
        # State transition succeeded, record event
        event = CallEvent(
            call_id=call_id,
            event_type="STATUS_CHANGE",
            payload={"from_status": from_status, "to_status": to_status}
        )
        db.add(event)
        db.commit()
        logger.info(f"Transition call {call_id} from {from_status} to {to_status} successful")
        return True
    
    logger.warning(
        f"Transition call {call_id} from {from_status} to {to_status} rejected: "
        f"current state does not match expected starting state '{from_status}'"
    )
    return False
