import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from app.models.call import Call
from app.models.tag import CallTag

logger = logging.getLogger(__name__)


def get_analytics_summary(
    db: Session,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> dict:
    """
    Aggregates call analytics: counts by status, sentiment distribution,
    conversion rate (COMPLETED calls with outcome=converted), and volume by day.
    """
    query = db.query(Call)
    if date_from:
        query = query.filter(Call.uploaded_at >= date_from)
    if date_to:
        query = query.filter(Call.uploaded_at <= date_to)

    all_calls = query.all()
    total = len(all_calls)

    if total == 0:
        return {
            "total_calls": 0,
            "by_status": {},
            "conversion_rate": 0.0,
            "sentiment_distribution": {},
            "avg_duration_seconds": None,
            "volume_by_day": [],
        }

    # --- counts by status ---
    by_status: dict[str, int] = {}
    for call in all_calls:
        by_status[call.status] = by_status.get(call.status, 0) + 1

    # --- avg duration ---
    durations = [c.duration_seconds for c in all_calls if c.duration_seconds is not None]
    avg_duration = sum(durations) / len(durations) if durations else None

    # --- effective tags per call (override > model) ---
    def _effective_tags_for(call: Call) -> dict:
        effective = {}
        for t in call.tags:
            cat = t.tag_category
            if cat not in effective or t.source == "override":
                effective[cat] = t
        return effective

    # --- sentiment distribution ---
    sentiment_counts: dict[str, int] = {}
    converted = 0
    for call in all_calls:
        eff = _effective_tags_for(call)
        sent_tag = eff.get("sentiment")
        if sent_tag:
            val = sent_tag.tag_value
            sentiment_counts[val] = sentiment_counts.get(val, 0) + 1
        outcome_tag = eff.get("outcome")
        if outcome_tag and outcome_tag.tag_value in ("converted", "sale_made", "deal_closed"):
            converted += 1

    completed = by_status.get("COMPLETED", 0) + by_status.get("DONE", 0)
    conversion_rate = round(converted / total * 100, 2) if total > 0 else 0.0

    # --- volume by day ---
    day_counts: dict[str, int] = {}
    for call in all_calls:
        if call.uploaded_at:
            day_key = call.uploaded_at.strftime("%Y-%m-%d")
            day_counts[day_key] = day_counts.get(day_key, 0) + 1

    volume_by_day = [
        {"date": d, "count": c} for d, c in sorted(day_counts.items())
    ]

    return {
        "total_calls": total,
        "by_status": by_status,
        "conversion_rate": conversion_rate,
        "converted_calls": converted,
        "sentiment_distribution": sentiment_counts,
        "avg_duration_seconds": round(avg_duration, 2) if avg_duration is not None else None,
        "volume_by_day": volume_by_day,
    }
