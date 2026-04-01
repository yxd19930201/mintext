from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.chapter_content import ChapterContent
from app.repositories.base import BaseRepository


class ChapterContentRepository(BaseRepository[ChapterContent]):
    def __init__(self, db: AsyncSession):
        super().__init__(ChapterContent, db)

    async def get_by_chapter(self, chapter_id: int, skip: int = 0, limit: int = 100) -> List[ChapterContent]:
        stmt = select(ChapterContent).where(ChapterContent.chapter_id == chapter_id).offset(skip).limit(limit).order_by(ChapterContent.version.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_latest(self, chapter_id: int) -> Optional[ChapterContent]:
        stmt = select(ChapterContent).where(ChapterContent.chapter_id == chapter_id).order_by(ChapterContent.version.desc()).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
