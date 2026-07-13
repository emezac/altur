import pytest
from app.models.call import Call
from app.models.event import CallEvent
from app.services.state_machine import transition

def _make_call(db, status="PENDING") -> Call:
    c = Call(
        filename="state_test.wav",
        storage_path="path/state_test.wav",
        mime_type="audio/wav",
        file_size_bytes=128,
        status=status,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c

def test_transition_success(db):
    call = _make_call(db, status="PENDING")
    
    # 1. Transition PENDING -> TRANSCRIBING
    success = transition(db, call.id, from_status="PENDING", to_status="TRANSCRIBING")
    assert success is True
    
    db.refresh(call)
    assert call.status == "TRANSCRIBING"
    
    # Verify CallEvent
    event = db.query(CallEvent).filter(CallEvent.call_id == call.id).order_by(CallEvent.created_at.desc()).first()
    assert event is not None
    assert event.event_type == "STATUS_CHANGE"
    assert event.payload["from_status"] == "PENDING"
    assert event.payload["to_status"] == "TRANSCRIBING"

def test_transition_invalid_from_state(db):
    call = _make_call(db, status="PENDING")
    
    # Try transitioning TRANSCRIBING -> TRANSCRIBED when it is PENDING
    success = transition(db, call.id, from_status="TRANSCRIBING", to_status="TRANSCRIBED")
    assert success is False
    
    db.refresh(call)
    assert call.status == "PENDING"  # Status remains unchanged
    
    # Verify no new status change events were registered
    events = db.query(CallEvent).filter(CallEvent.call_id == call.id).all()
    # There should only be the initial event from creation if any, none from this failed transition
    status_change_events = [e for e in events if e.payload.get("to_status") == "TRANSCRIBED"]
    assert len(status_change_events) == 0

def test_transition_non_existent_call(db):
    success = transition(db, "non-existent-uuid-123", from_status="PENDING", to_status="TRANSCRIBING")
    assert success is False
