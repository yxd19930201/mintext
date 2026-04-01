from typing import List
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.project_repo import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectRead


class ProjectService:
    def __init__(self, db: AsyncSession):
        self.repo = ProjectRepository(db)

    async def list_projects(self, owner_id: int, skip: int = 0, limit: int = 20) -> List[ProjectRead]:
        projects = await self.repo.list(skip=skip, limit=limit, owner_id=owner_id)
        return [ProjectRead.model_validate(p) for p in projects]

    async def get_project(self, project_id: int, owner_id: int) -> ProjectRead:
        project = await self.repo.get(project_id)
        if not project or project.owner_id != owner_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        return ProjectRead.model_validate(project)

    async def create_project(self, data: ProjectCreate, owner_id: int) -> ProjectRead:
        project = await self.repo.create(**data.model_dump(), owner_id=owner_id)
        return ProjectRead.model_validate(project)

    async def update_project(self, project_id: int, data: ProjectUpdate, owner_id: int) -> ProjectRead:
        project = await self.repo.get(project_id)
        if not project or project.owner_id != owner_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        updated = await self.repo.update(project, **data.model_dump(exclude_none=True))
        return ProjectRead.model_validate(updated)

    async def delete_project(self, project_id: int, owner_id: int) -> None:
        project = await self.repo.get(project_id)
        if not project or project.owner_id != owner_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        await self.repo.delete(project)
