from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.db import get_db
from app.core.config import settings

router = APIRouter()


def check_redis() -> bool:
    """
    Probes Redis with a 1-second timeout.
    Returns True when no REDIS_URL is configured (fakeredis / local dev).
    """
    if not settings.REDIS_URL or not settings.REDIS_URL.strip():
        return True
    try:
        import redis
        r = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1)
        return bool(r.ping())
    except Exception:
        return False


def check_queue_available() -> bool:
    """
    Returns True if the queue (Redis) is reachable.
    Exposed as a standalone helper so upload endpoints can call it directly.
    """
    return check_redis()


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    """
    Returns the operational status of the DB and queue.
    HTTP 200 when healthy, HTTP 503 when any critical component is down.
    """
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    queue_ok = check_redis()
    healthy = db_ok and queue_ok

    payload = {
        "status": "ok" if healthy else "unhealthy",
        "db": db_ok,
        "queue": queue_ok,
    }
    return JSONResponse(
        status_code=200 if healthy else 503,
        content=payload,
    )
