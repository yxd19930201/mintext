from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ai_config import AIConfig
from app.repositories.base import BaseRepository


class AIConfigRepository(BaseRepository[AIConfig]):
    def __init__(self, db: AsyncSession):
        super().__init__(AIConfig, db)

    async def get_default(self) -> AIConfig | None:
        result = await self.db.execute(select(AIConfig).where(AIConfig.is_default == True))
        return result.scalar_one_or_none()

    async def clear_default(self) -> None:
        await self.db.execute(update(AIConfig).values(is_default=False))
        await self.db.flush()
