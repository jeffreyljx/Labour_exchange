from __future__ import annotations

import redis as redis_lib

from app.config import settings

_client: redis_lib.Redis | None = None


def get_redis_client() -> redis_lib.Redis:
    global _client
    if _client is None:
        _client = redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)
    return _client
