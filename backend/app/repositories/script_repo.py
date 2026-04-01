from sqlalchemy.ext.asyncio import AsyncSession
from app.models.script import Script
from app.repositories.base import BaseRepository


class ScriptRepository(BaseRepository[Script]):
    def __init__(self, db: AsyncSession):
        super().__init__(Script, db)
