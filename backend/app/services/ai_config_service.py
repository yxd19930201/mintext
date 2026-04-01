from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.ai_config_repo import AIConfigRepository
from app.repositories.ai_prompt_preset_repo import AIPromptPresetRepository
from app.schemas.ai_config import AIConfigCreate, AIConfigUpdate, AIConfigRead
from app.schemas.ai_prompt_preset import AIPromptPresetCreate, AIPromptPresetUpdate, AIPromptPresetRead


class AIConfigService:
    def __init__(self, db: AsyncSession):
        self.config_repo = AIConfigRepository(db)
        self.preset_repo = AIPromptPresetRepository(db)

    # --- AI Configs ---

    async def list_configs(self) -> list[AIConfigRead]:
        configs = await self.config_repo.list(limit=100)
        return [AIConfigRead.model_validate(c) for c in configs]

    async def create_config(self, data: AIConfigCreate) -> AIConfigRead:
        if data.is_default:
            await self.config_repo.clear_default()
        config = await self.config_repo.create(**data.model_dump())
        return AIConfigRead.model_validate(config)

    async def update_config(self, config_id: int, data: AIConfigUpdate) -> AIConfigRead:
        config = await self.config_repo.get(config_id)
        if not config:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI config not found")
        if data.is_default:
            await self.config_repo.clear_default()
        updated = await self.config_repo.update(config, **data.model_dump(exclude_none=True))
        return AIConfigRead.model_validate(updated)

    async def delete_config(self, config_id: int) -> None:
        config = await self.config_repo.get(config_id)
        if not config:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI config not found")
        await self.config_repo.delete(config)

    # --- Prompt Presets ---

    async def list_presets(self) -> list[AIPromptPresetRead]:
        presets = await self.preset_repo.list(limit=100)
        return [AIPromptPresetRead.model_validate(p) for p in presets]

    async def create_preset(self, data: AIPromptPresetCreate) -> AIPromptPresetRead:
        preset = await self.preset_repo.create(**data.model_dump())
        return AIPromptPresetRead.model_validate(preset)

    async def update_preset(self, preset_id: int, data: AIPromptPresetUpdate) -> AIPromptPresetRead:
        preset = await self.preset_repo.get(preset_id)
        if not preset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt preset not found")
        updated = await self.preset_repo.update(preset, **data.model_dump(exclude_none=True))
        return AIPromptPresetRead.model_validate(updated)

    async def delete_preset(self, preset_id: int) -> None:
        preset = await self.preset_repo.get(preset_id)
        if not preset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt preset not found")
        await self.preset_repo.delete(preset)
