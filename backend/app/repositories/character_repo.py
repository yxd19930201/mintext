from sqlalchemy.ext.asyncio import AsyncSession
from app.models.character import Character
from app.repositories.base import BaseRepository


class CharacterRepository(BaseRepository[Character]):
    def __init__(self, db: AsyncSession):
        super().__init__(Character, db)
