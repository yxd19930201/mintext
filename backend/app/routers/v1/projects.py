from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.services.project_service import ProjectService
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectRead
from app.schemas.common import ApiResponse, PaginatedResponse

router = APIRouter()


@router.get("", response_model=PaginatedResponse[ProjectRead])
async def list_projects(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    projects = await ProjectService(db).list_projects(user_id, skip, limit)
    return PaginatedResponse(data=projects, total=len(projects), page=skip // limit + 1, page_size=limit)


@router.post("", response_model=ApiResponse[ProjectRead], status_code=201)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    project = await ProjectService(db).create_project(data, user_id)
    return ApiResponse(data=project)


@router.get("/{project_id}", response_model=ApiResponse[ProjectRead])
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    project = await ProjectService(db).get_project(project_id, user_id)
    return ApiResponse(data=project)


@router.patch("/{project_id}", response_model=ApiResponse[ProjectRead])
async def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    project = await ProjectService(db).update_project(project_id, data, user_id)
    return ApiResponse(data=project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    await ProjectService(db).delete_project(project_id, user_id)
