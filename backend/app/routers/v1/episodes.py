from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.services.episode_service import EpisodeService
from app.schemas.episode import EpisodeCreate, EpisodeUpdate, EpisodeRead
from app.schemas.common import ApiResponse, PaginatedResponse

router = APIRouter()


@router.get("/{project_id}/episodes", response_model=PaginatedResponse[EpisodeRead])
async def list_episodes(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    episodes = await EpisodeService(db).list_episodes(project_id, user_id)
    return PaginatedResponse(data=episodes, total=len(episodes))


@router.post("/{project_id}/episodes", response_model=ApiResponse[EpisodeRead], status_code=201)
async def create_episode(
    project_id: int,
    data: EpisodeCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    episode = await EpisodeService(db).create_episode(project_id, data, user_id)
    return ApiResponse(data=episode)


@router.get("/{project_id}/episodes/{episode_id}", response_model=ApiResponse[EpisodeRead])
async def get_episode(
    project_id: int,
    episode_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    episode = await EpisodeService(db).get_episode(episode_id, user_id)
    return ApiResponse(data=episode)


@router.patch("/{project_id}/episodes/{episode_id}", response_model=ApiResponse[EpisodeRead])
async def update_episode(
    project_id: int,
    episode_id: int,
    data: EpisodeUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    episode = await EpisodeService(db).update_episode(episode_id, data, user_id)
    return ApiResponse(data=episode)


@router.delete("/{project_id}/episodes/{episode_id}", status_code=204)
async def delete_episode(
    project_id: int,
    episode_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    await EpisodeService(db).delete_episode(episode_id, user_id)
