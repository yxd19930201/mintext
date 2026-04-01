from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.chapter import Chapter
from app.repositories.base import BaseRepository


class ChapterRepository(BaseRepository[Chapter]):
    def __init__(self, db: AsyncSession):
        super().__init__(Chapter, db)

    async def get_by_novel(self, novel_id: int, skip: int = 0, limit: int = 1000) -> List[Chapter]:
        stmt = select(Chapter).where(Chapter.novel_id == novel_id).offset(skip).limit(limit).order_by(Chapter.chapter_number)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_number(self, novel_id: int, chapter_number: int) -> Optional[Chapter]:
        stmt = select(Chapter).where(Chapter.novel_id == novel_id, Chapter.chapter_number == chapter_number)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_last_chapter(self, novel_id: int) -> Optional[Chapter]:
        stmt = select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.chapter_number.desc()).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
