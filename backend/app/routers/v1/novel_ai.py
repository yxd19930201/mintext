from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.services.novel_generate_service import NovelGenerateService
from app.schemas.novel_generate import (
    GenerateNovelOutlineRequest,
    GenerateChapterRequest,
    BatchGenerateChaptersRequest,
    GenerateNextChapterRequest,
    OutlineResult,
    GenerateChapterResult,
    BatchGenerateResult,
    GenerateNextChapterResult,
)
from app.schemas.common import ApiResponse

router = APIRouter()


@router.post("/generate/outline", response_model=ApiResponse[OutlineResult])
async def generate_outline(
    req: GenerateNovelOutlineRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    result = await NovelGenerateService(db).generate_outline(req, user_id)
    return ApiResponse(data=result)


@router.post("/generate/chapter/{chapter_id}", response_model=ApiResponse[GenerateChapterResult])
async def generate_chapter(
    chapter_id: int,
    req: GenerateChapterRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    result = await NovelGenerateService(db).generate_chapter_content(chapter_id, req, user_id)
    return ApiResponse(data=result)


@router.post("/generate/batch/{novel_id}", response_model=ApiResponse[BatchGenerateResult])
async def batch_generate_chapters(
    novel_id: int,
    req: BatchGenerateChaptersRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    result = await NovelGenerateService(db).batch_generate_chapters(novel_id, req, user_id)
    return ApiResponse(data=result)


@router.post("/generate/next/{novel_id}", response_model=ApiResponse[GenerateNextChapterResult])
async def generate_next_chapter(
    novel_id: int,
    req: GenerateNextChapterRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    result = await NovelGenerateService(db).generate_next_chapter(novel_id, req, user_id)
    return ApiResponse(data=result)
