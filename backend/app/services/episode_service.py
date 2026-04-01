from typing import List
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.episode_repo import EpisodeRepository
from app.repositories.project_repo import ProjectRepository
from app.schemas.episode import EpisodeCreate, EpisodeUpdate, EpisodeRead


class EpisodeService:
    def __init__(self, db: AsyncSession):
        self.repo = EpisodeRepository(db)
        self.project_repo = ProjectRepository(db)

    async def _check_project(self, project_id: int, owner_id: int):
        project = await self.project_repo.get(project_id)
        if not project or project.owner_id != owner_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    async def list_episodes(self, project_id: int, owner_id: int) -> List[EpisodeRead]:
        await self._check_project(project_id, owner_id)
        episodes = await self.repo.list(project_id=project_id)
        return [EpisodeRead.model_validate(e) for e in episodes]

    async def create_episode(self, project_id: int, data: EpisodeCreate, owner_id: int) -> EpisodeRead:
        await self._check_project(project_id, owner_id)
        episode = await self.repo.create(**data.model_dump(), project_id=project_id)
        return EpisodeRead.model_validate(episode)

    async def get_episode(self, episode_id: int, owner_id: int) -> EpisodeRead:
        episode = await self.repo.get(episode_id)
        if not episode:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episode not found")
        await self._check_project(episode.project_id, owner_id)
        return EpisodeRead.model_validate(episode)

    async def update_episode(self, episode_id: int, data: EpisodeUpdate, owner_id: int) -> EpisodeRead:
        episode = await self.repo.get(episode_id)
        if not episode:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episode not found")
        await self._check_project(episode.project_id, owner_id)
        updated = await self.repo.update(episode, **data.model_dump(exclude_none=True))
        return EpisodeRead.model_validate(updated)

    async def delete_episode(self, episode_id: int, owner_id: int) -> None:
        episode = await self.repo.get(episode_id)
        if not episode:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episode not found")
        await self._check_project(episode.project_id, owner_id)
        await self.repo.delete(episode)
