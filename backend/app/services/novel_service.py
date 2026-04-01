from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from app.models.novel import Novel
from app.repositories.novel_repo import NovelRepository
from app.schemas.novel import NovelCreate, NovelUpdate


class NovelService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = NovelRepository(db)

    async def list_novels(self, owner_id: int, skip: int = 0, limit: int = 100) -> List[Novel]:
        return await self.repo.get_by_owner(owner_id, skip, limit)

    async def get_novel(self, novel_id: int, owner_id: int) -> Novel:
        novel = await self.repo.get_by_id_and_owner(novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")
        return novel

    async def create_novel(self, data: NovelCreate, owner_id: int) -> Novel:
        novel = await self.repo.create(
            title=data.title,
            genre=data.genre,
            synopsis=data.synopsis,
            total_chapters=data.total_chapters,
            owner_id=owner_id,
            ai_config_id=data.ai_config_id,
            system_prompt=data.system_prompt,
        )
        await self.db.commit()
        return novel

    async def update_novel(self, novel_id: int, data: NovelUpdate, owner_id: int) -> Novel:
        novel = await self.get_novel(novel_id, owner_id)
        update_data = data.model_dump(exclude_unset=True)
        novel = await self.repo.update(novel, **update_data)
        await self.db.commit()
        return novel

    async def delete_novel(self, novel_id: int, owner_id: int) -> None:
        novel = await self.get_novel(novel_id, owner_id)
        await self.repo.delete(novel)
        await self.db.commit()
