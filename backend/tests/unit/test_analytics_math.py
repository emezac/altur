import pytest
from datetime import datetime, timezone
from app.models.call import Call
from app.models.tag import CallTag
from app.services.analytics_service import get_analytics_summary

def _make_call_with_tags(db, filename, status="COMPLETED", duration=60.0, tags=None) -> Call:
    c = Call(
        filename=filename,
        storage_path=f"path/{filename}",
        mime_type="audio/wav",
        file_size_bytes=1000,
        status=status,
        duration_seconds=duration,
        uploaded_at=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    
    if tags:
        for cat, val, source in tags:
            tag_row = CallTag(
                call_id=c.id,
                tag_category=cat,
                tag_value=val,
                confidence=1.0,
                source=source
            )
            db.add(tag_row)
        db.commit()
        db.refresh(c)
    return c

def test_analytics_math_conversion_rate(db):
    # 3 completed calls: 2 converted, 1 follow up
    _make_call_with_tags(db, "call1.wav", tags=[("outcome", "won_deal_closed", "model")])
    _make_call_with_tags(db, "call2.wav", tags=[("outcome", "deal_closed", "override")])
    _make_call_with_tags(db, "call3.wav", tags=[("outcome", "follow_up_scheduled", "model")])
    
    summary = get_analytics_summary(db)
    assert summary["total_calls"] == 3
    assert summary["converted_calls"] == 2
    assert summary["conversion_rate"] == 66.67  # round(2/3 * 100, 2)

def test_analytics_avg_duration(db):
    _make_call_with_tags(db, "call1.wav", duration=120.5)
    _make_call_with_tags(db, "call2.wav", duration=90.0)
    _make_call_with_tags(db, "call3.wav", duration=None)  # Ignored from avg duration
    
    summary = get_analytics_summary(db)
    assert summary["avg_duration_seconds"] == 105.25  # round((120.5 + 90.0) / 2, 2)

def test_analytics_top_objection_price_budget(db):
    # 3 calls: 2 price_budget, 1 timing_schedule
    _make_call_with_tags(db, "call1.wav", tags=[("objection", "price_budget", "model")])
    _make_call_with_tags(db, "call2.wav", tags=[("objection", "price_budget", "model")])
    _make_call_with_tags(db, "call3.wav", tags=[("objection", "timing_schedule", "model")])
    
    summary = get_analytics_summary(db)
    assert summary["top_objection"] == "price_budget"

def test_analytics_top_objection_all_no_objections_raised(db):
    _make_call_with_tags(db, "call1.wav", tags=[("objection", "no_objections_raised", "model")])
    _make_call_with_tags(db, "call2.wav", tags=[("objection", "no_objections_raised", "override")])
    
    summary = get_analytics_summary(db)
    assert summary["top_objection"] is None  # all no_objections_raised -> None

def test_analytics_top_objection_empty(db):
    summary = get_analytics_summary(db)
    assert summary["total_calls"] == 0
    assert summary["top_objection"] is None
