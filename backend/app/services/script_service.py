from typing import List
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.script_repo import ScriptRepository
from app.repositories.episode_repo import EpisodeRepository
from app.schemas.script import ScriptCreate, ScriptUpdate, ScriptRead


class ScriptService:
    def __init__(self, db: AsyncSession):
        self.repo = ScriptRepository(db)
        self.episode_repo = EpisodeRepository(db)

    async def _check_episode(self, episode_id: int):
        episode = await self.episode_repo.get(episode_id)
        if not episode:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episode not found")
        return episode

    async def list_scripts(self, episode_id: int) -> List[ScriptRead]:
        await self._check_episode(episode_id)
        scripts = await self.repo.list(episode_id=episode_id)
        return [ScriptRead.model_validate(s) for s in scripts]

    async def create_script(self, episode_id: int, data: ScriptCreate) -> ScriptRead:
        await self._check_episode(episode_id)
        script = await self.repo.create(**data.model_dump(), episode_id=episode_id)
        return ScriptRead.model_validate(script)

    async def get_script(self, script_id: int) -> ScriptRead:
        script = await self.repo.get(script_id)
        if not script:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Script not found")
        return ScriptRead.model_validate(script)

    async def update_script(self, script_id: int, data: ScriptUpdate) -> ScriptRead:
        script = await self.repo.get(script_id)
        if not script:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Script not found")
        updated = await self.repo.update(script, **data.model_dump(exclude_none=True))
        return ScriptRead.model_validate(updated)

    async def delete_script(self, script_id: int) -> None:
        script = await self.repo.get(script_id)
        if not script:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Script not found")
        await self.repo.delete(script)
