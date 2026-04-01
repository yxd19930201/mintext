from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.novel import Novel
from app.repositories.base import BaseRepository


class NovelRepository(BaseRepository[Novel]):
    def __init__(self, db: AsyncSession):
        super().__init__(Novel, db)

    async def get_by_owner(self, owner_id: int, skip: int = 0, limit: int = 100) -> List[Novel]:
        stmt = select(Novel).where(Novel.owner_id == owner_id).offset(skip).limit(limit).order_by(Novel.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id_and_owner(self, novel_id: int, owner_id: int) -> Optional[Novel]:
        stmt = select(Novel).where(Novel.id == novel_id, Novel.owner_id == owner_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
