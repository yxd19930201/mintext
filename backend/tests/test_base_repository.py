import unittest
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all mapped tables
from app.models.base import Base
from app.models.novel import Novel
from app.repositories.base import BaseRepository
from app.repositories.novel_repo import NovelRepository


class BaseRepositoryDeleteTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_awaits_async_session_and_flushes(self):
        session = AsyncMock()
        repository = BaseRepository(Base, session)
        record = object()

        await repository.delete(record)

        session.delete.assert_awaited_once_with(record)
        session.flush.assert_awaited_once_with()

    async def test_deleted_record_is_absent_in_a_new_database_session(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessions() as session:
            novel = Novel(title="待删除", synopsis="测试", owner_id=1)
            session.add(novel)
            await session.commit()
            novel_id = novel.id
            await NovelRepository(session).delete(novel)
            await session.commit()

        async with sessions() as session:
            self.assertIsNone(await NovelRepository(session).get(novel_id))
        await engine.dispose()


if __name__ == "__main__":
    unittest.main()
