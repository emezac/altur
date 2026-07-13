from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.db import get_db
from app.core.config import settings

router = APIRouter()

def check_redis() -> bool:
    if not settings.REDIS_URL or not settings.REDIS_URL.strip():
        return True
    try:
        import redis
        # Timeout corto de 1 segundo para no colgar la petición
        r = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1)
        return r.ping()
    except Exception:
        return False

@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    
    queue_ok = check_redis()
    
    status_code = 200
    if not db_ok or not queue_ok:
        # En caso de fallo de algún componente crítico, podemos retornar 503
        status_code = 503
        
    return {
        "status": "ok" if (db_ok and queue_ok) else "unhealthy",
        "db": db_ok,
        "queue": queue_ok
    }
