"""
RQ worker entrypoint.

Started via the Procfile `worker` process and the docker-compose `worker` service.
Unlike `python -m rq worker -u $REDIS_URL`, this uses `get_connection()` so the
connection is built with the right options for the environment — in particular
`ssl_cert_reqs=None` for Heroku's self-signed `rediss://` TLS certificate.
"""
import logging

from rq import Queue, Worker

from app.core.logging import setup_logging
from app.workers.queue import get_connection

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    conn = get_connection()
    queue = Queue("default", connection=conn)
    logger.info("Starting RQ worker on the 'default' queue")
    Worker([queue], connection=conn).work()


if __name__ == "__main__":
    main()
