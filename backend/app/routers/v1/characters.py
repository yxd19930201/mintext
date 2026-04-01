from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.repositories.character_repo import CharacterRepository
from app.repositories.project_repo import ProjectRepository
from app.schemas.character import CharacterCreate, CharacterUpdate, CharacterRead
from app.schemas.common import ApiResponse, PaginatedResponse
from fastapi import HTTPException, status

router = APIRouter()


@router.get("/{project_id}/characters", response_model=PaginatedResponse[CharacterRead])
async def list_characters(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    project = await ProjectRepository(db).get(project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    chars = await CharacterRepository(db).list(project_id=project_id)
    return PaginatedResponse(data=[CharacterRead.model_validate(c) for c in chars], total=len(chars))


@router.post("/{project_id}/characters", response_model=ApiResponse[CharacterRead], status_code=201)
async def create_character(
    project_id: int,
    data: CharacterCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    project = await ProjectRepository(db).get(project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    char = await CharacterRepository(db).create(**data.model_dump(), project_id=project_id)
    return ApiResponse(data=CharacterRead.model_validate(char))


@router.patch("/{project_id}/characters/{character_id}", response_model=ApiResponse[CharacterRead])
async def update_character(
    project_id: int,
    character_id: int,
    data: CharacterUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    project = await ProjectRepository(db).get(project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    repo = CharacterRepository(db)
    char = await repo.get(character_id)
    if not char or char.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    updated = await repo.update(char, **data.model_dump(exclude_none=True))
    return ApiResponse(data=CharacterRead.model_validate(updated))


@router.delete("/{project_id}/characters/{character_id}", status_code=204)
async def delete_character(
    project_id: int,
    character_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    project = await ProjectRepository(db).get(project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    repo = CharacterRepository(db)
    char = await repo.get(character_id)
    if not char or char.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    await repo.delete(char)
