import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services.analytics_service import get_analytics_summary

router = APIRouter(prefix="/analytics")
logger = logging.getLogger(__name__)


@router.get("/summary")
def analytics_summary(
    date_from: Optional[datetime] = Query(None, description="Start of date range (ISO 8601)"),
    date_to: Optional[datetime] = Query(None, description="End of date range (ISO 8601)"),
    db: Session = Depends(get_db),
):
    """
    Returns aggregated analytics across all calls:
    - Total count and breakdown by status
    - Sentiment distribution
    - Conversion rate (outcome=converted)
    - Average call duration
    - Call volume grouped by day
    """
    return get_analytics_summary(db=db, date_from=date_from, date_to=date_to)
