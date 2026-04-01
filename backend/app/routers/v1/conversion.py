from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.services.conversion_service import ConversionService
from app.schemas.conversion import (
    NovelToScriptRequest,
    ScriptToVideoRequest,
    NovelToScriptResult,
    ScriptToVideoResult,
)
from app.schemas.common import ApiResponse

router = APIRouter()


@router.post("/novel-to-script", response_model=ApiResponse[NovelToScriptResult])
async def convert_novel_to_script(
    req: NovelToScriptRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """将小说文本转换为短剧剧本"""
    result = await ConversionService(db).novel_to_script(req, user_id)
    return ApiResponse(data=result)


@router.post("/script-to-video", response_model=ApiResponse[ScriptToVideoResult])
async def convert_script_to_video(
    req: ScriptToVideoRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """将短剧剧本转换为 Seedance 2.0 视频生成格式"""
    result = await ConversionService(db).script_to_video(req, user_id)
    return ApiResponse(data=result)
