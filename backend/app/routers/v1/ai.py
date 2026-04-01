from fastapi import APIRouter, Depends, Body
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.services.ai_config_service import AIConfigService
from app.services.ai_generate_service import AIGenerateService
from app.schemas.ai_config import AIConfigCreate, AIConfigUpdate, AIConfigRead
from app.schemas.ai_prompt_preset import AIPromptPresetCreate, AIPromptPresetUpdate, AIPromptPresetRead
from app.schemas.ai_generate import GenerateOutlineRequest, GenerateScriptRequest, BatchGenerateRequest, GenerateNextEpisodeRequest, OutlineResult
from app.schemas.common import ApiResponse

router = APIRouter()


# --- AI Configs ---

@router.get("/configs", response_model=ApiResponse[list[AIConfigRead]])
async def list_configs(db: AsyncSession = Depends(get_db)):
    configs = await AIConfigService(db).list_configs()
    return ApiResponse(data=configs)


@router.post("/configs", response_model=ApiResponse[AIConfigRead], status_code=201)
async def create_config(data: AIConfigCreate, db: AsyncSession = Depends(get_db)):
    config = await AIConfigService(db).create_config(data)
    return ApiResponse(data=config)


@router.patch("/configs/{config_id}", response_model=ApiResponse[AIConfigRead])
async def update_config(config_id: int, data: AIConfigUpdate, db: AsyncSession = Depends(get_db)):
    config = await AIConfigService(db).update_config(config_id, data)
    return ApiResponse(data=config)


@router.delete("/configs/{config_id}", status_code=204)
async def delete_config(config_id: int, db: AsyncSession = Depends(get_db)):
    await AIConfigService(db).delete_config(config_id)


# --- Prompt Presets ---

@router.get("/prompts", response_model=ApiResponse[list[AIPromptPresetRead]])
async def list_presets(db: AsyncSession = Depends(get_db)):
    presets = await AIConfigService(db).list_presets()
    return ApiResponse(data=presets)


@router.post("/prompts", response_model=ApiResponse[AIPromptPresetRead], status_code=201)
async def create_preset(data: AIPromptPresetCreate, db: AsyncSession = Depends(get_db)):
    preset = await AIConfigService(db).create_preset(data)
    return ApiResponse(data=preset)


@router.patch("/prompts/{preset_id}", response_model=ApiResponse[AIPromptPresetRead])
async def update_preset(preset_id: int, data: AIPromptPresetUpdate, db: AsyncSession = Depends(get_db)):
    preset = await AIConfigService(db).update_preset(preset_id, data)
    return ApiResponse(data=preset)


@router.delete("/prompts/{preset_id}", status_code=204)
async def delete_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    await AIConfigService(db).delete_preset(preset_id)


# --- Generate ---

@router.post("/generate/outline", response_model=ApiResponse[OutlineResult])
async def generate_outline(
    req: GenerateOutlineRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    result = await AIGenerateService(db).generate_outline(req, user_id)
    return ApiResponse(data=result)


@router.post("/generate/script/{episode_id}", response_model=ApiResponse[dict])
async def generate_script(
    episode_id: int,
    req: Optional[GenerateScriptRequest] = Body(default=None),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    if req is None:
        req = GenerateScriptRequest()
    result = await AIGenerateService(db).generate_script_for_episode(episode_id, req, user_id)
    return ApiResponse(data=result)


@router.post("/generate/batch/{project_id}", response_model=ApiResponse[dict])
async def batch_generate(
    project_id: int,
    req: Optional[BatchGenerateRequest] = Body(default=None),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    if req is None:
        req = BatchGenerateRequest(project_id=project_id)
    else:
        req.project_id = project_id
    result = await AIGenerateService(db).batch_generate(req, user_id)
    return ApiResponse(data=result)


@router.post("/generate/next/{project_id}", response_model=ApiResponse[dict])
async def generate_next_episode(
    project_id: int,
    req: Optional[GenerateNextEpisodeRequest] = Body(default=None),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    if req is None:
        req = GenerateNextEpisodeRequest(project_id=project_id)
    else:
        req.project_id = project_id
    result = await AIGenerateService(db).generate_next_episode(req, user_id)
    return ApiResponse(data=result)
