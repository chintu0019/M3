"""
M3 Worker Entry Point -- runs the ARQ worker process.
"""

import logging

from arq import run_worker
from arq.connections import RedisSettings

from m3.config import load_settings
from m3.workers.tasks import WorkerSettings


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    settings = load_settings()

    # Parse Redis URL into ARQ RedisSettings
    redis_url = settings.redis.url
    # redis://host:port/db
    if redis_url.startswith("redis://"):
        parts = redis_url.replace("redis://", "").split(":")
        host = parts[0]
        port = int(parts[1].split("/")[0]) if len(parts) > 1 else 6379
        WorkerSettings.redis_settings = RedisSettings(host=host, port=port)
    else:
        WorkerSettings.redis_settings = RedisSettings()

    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
