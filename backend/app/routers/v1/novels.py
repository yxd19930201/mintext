from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.services.novel_service import NovelService
from app.schemas.novel import NovelCreate, NovelUpdate, NovelRead
from app.schemas.common import ApiResponse, PaginatedResponse

router = APIRouter()


@router.get("", response_model=PaginatedResponse[NovelRead])
async def list_novels(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    novels = await NovelService(db).list_novels(user_id, skip, limit)
    return PaginatedResponse(data=novels, total=len(novels), page=skip // limit + 1, page_size=limit)


@router.post("", response_model=ApiResponse[NovelRead], status_code=201)
async def create_novel(
    data: NovelCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    novel = await NovelService(db).create_novel(data, user_id)
    return ApiResponse(data=novel)


@router.get("/{novel_id}", response_model=ApiResponse[NovelRead])
async def get_novel(
    novel_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    novel = await NovelService(db).get_novel(novel_id, user_id)
    return ApiResponse(data=novel)


@router.patch("/{novel_id}", response_model=ApiResponse[NovelRead])
async def update_novel(
    novel_id: int,
    data: NovelUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    novel = await NovelService(db).update_novel(novel_id, data, user_id)
    return ApiResponse(data=novel)


@router.delete("/{novel_id}", status_code=204)
async def delete_novel(
    novel_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    await NovelService(db).delete_novel(novel_id, user_id)
