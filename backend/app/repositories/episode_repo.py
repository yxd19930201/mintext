from sqlalchemy.ext.asyncio import AsyncSession
from app.models.episode import Episode
from app.repositories.base import BaseRepository


class EpisodeRepository(BaseRepository[Episode]):
    def __init__(self, db: AsyncSession):
        super().__init__(Episode, db)
