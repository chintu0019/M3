"""
M3 API Dependencies — shared FastAPI dependency injectors.
"""

from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from m3.config import Settings
from m3.storage.cache import Cache
from m3.storage.files import FileStore

security = HTTPBearer()


async def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with request.app.state.db() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_files(request: Request) -> FileStore:
    return request.app.state.files


async def get_cache(request: Request) -> Cache:
    return request.app.state.cache


async def verify_auth(
    settings: Settings = Depends(get_settings),
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> str:
    """Verify the Bearer token matches the configured API key."""
    if not settings.auth.api_key:
        return "anonymous"
    if credentials.credentials != settings.auth.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return credentials.credentials
