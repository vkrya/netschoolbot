import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from app.db.engine import Database
from app.db.repositories import (
    CacheRepository,
    MarkStateRepository,
    MiniappRepository,
    SessionRepository,
    UserRepository,
)


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    database = Database(tmp_path / "test.sqlite3")
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest_asyncio.fixture
async def users(db) -> UserRepository:
    return UserRepository(db)


@pytest_asyncio.fixture
async def marks(db) -> MarkStateRepository:
    return MarkStateRepository(db)


@pytest_asyncio.fixture
async def sessions(db) -> SessionRepository:
    return SessionRepository(db)


@pytest_asyncio.fixture
async def miniapp(db) -> MiniappRepository:
    return MiniappRepository(db, login_code_ttl=600)


@pytest_asyncio.fixture
async def cache(db) -> CacheRepository:
    return CacheRepository(db)
