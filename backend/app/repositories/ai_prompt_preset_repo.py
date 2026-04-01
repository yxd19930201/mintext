from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ai_prompt_preset import AIPromptPreset
from app.repositories.base import BaseRepository


class AIPromptPresetRepository(BaseRepository[AIPromptPreset]):
    def __init__(self, db: AsyncSession):
        super().__init__(AIPromptPreset, db)
