"""
M3 Cache — Redis async wrapper.
"""

import json
from typing import Any

import redis.asyncio as aioredis


class Cache:
    def __init__(self, url: str):
        self.redis = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self.redis.get(key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        await self.redis.set(key, value, ex=ttl)

    async def delete(self, key: str) -> None:
        await self.redis.delete(key)

    async def get_json(self, key: str) -> Any | None:
        raw = await self.redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self.redis.set(key, json.dumps(value), ex=ttl)

    async def close(self) -> None:
        await self.redis.aclose()
