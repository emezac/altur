import redis
import logging
from rq import Queue
from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_connection = None

def get_connection():
    """
    Returns a cached Redis connection. If REDIS_URL is not set,
    returns a mock connection using fakeredis.
    """
    global _redis_connection
    if _redis_connection is not None:
        return _redis_connection
        
    url = settings.REDIS_URL
    if not url or not url.strip():
        import fakeredis
        logger.info("Initializing fake Redis connection using fakeredis.")
        _redis_connection = fakeredis.FakeStrictRedis()
    else:
        kwargs = {}
        if url.startswith("rediss://"):
            logger.info("Configuring secure Redis SSL connection (disabling certificate verification for self-signed Heroku certs).")
            kwargs["ssl_cert_reqs"] = None
        _redis_connection = redis.Redis.from_url(url, **kwargs)
        
    return _redis_connection

def get_queue() -> Queue:
    """
    Returns an RQ queue. If REDIS_URL is not set, the queue operates in
    synchronous/inline mode (is_async=False) using fakeredis.
    """
    conn = get_connection()
    url = settings.REDIS_URL
    is_async = bool(url and url.strip())
    
    if not is_async:
        logger.debug("RQ queue initialized in synchronous (is_async=False) mode using fakeredis.")
    else:
        logger.debug("RQ queue initialized in asynchronous mode connecting to Redis server.")
        
    return Queue("default", connection=conn, is_async=is_async)
