from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.script_service import ScriptService
from app.services.ai_service import ai_service
from app.services.generation_mode_service import resolve_generation_config
from app.repositories.ai_config_repo import AIConfigRepository
from app.schemas.script import ScriptCreate, ScriptUpdate, ScriptRead
from app.schemas.common import ApiResponse, PaginatedResponse

router = APIRouter()


@router.get("/{episode_id}/scripts", response_model=PaginatedResponse[ScriptRead])
async def list_scripts(episode_id: int, db: AsyncSession = Depends(get_db)):
    scripts = await ScriptService(db).list_scripts(episode_id)
    return PaginatedResponse(data=scripts, total=len(scripts))


@router.post("/{episode_id}/scripts", response_model=ApiResponse[ScriptRead], status_code=201)
async def create_script(episode_id: int, data: ScriptCreate, db: AsyncSession = Depends(get_db)):
    script = await ScriptService(db).create_script(episode_id, data)
    return ApiResponse(data=script)


@router.get("/{episode_id}/scripts/{script_id}", response_model=ApiResponse[ScriptRead])
async def get_script(episode_id: int, script_id: int, db: AsyncSession = Depends(get_db)):
    script = await ScriptService(db).get_script(script_id)
    return ApiResponse(data=script)


@router.patch("/{episode_id}/scripts/{script_id}", response_model=ApiResponse[ScriptRead])
async def update_script(episode_id: int, script_id: int, data: ScriptUpdate, db: AsyncSession = Depends(get_db)):
    script = await ScriptService(db).update_script(script_id, data)
    return ApiResponse(data=script)


@router.delete("/{episode_id}/scripts/{script_id}", status_code=204)
async def delete_script(episode_id: int, script_id: int, db: AsyncSession = Depends(get_db)):
    await ScriptService(db).delete_script(script_id)


@router.post("/{episode_id}/scripts/{script_id}/generate", response_model=ApiResponse[str])
async def generate_script(
    episode_id: int,
    script_id: int,
    options: dict = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
):
    """Trigger AI generation for a script. Returns generated content (placeholder)."""
    from app.schemas.script import ScriptUpdate
    script = await ScriptService(db).get_script(script_id)
    ai_config = await resolve_generation_config(AIConfigRepository(db), options)
    content = await ai_service.generate_script(script.ai_prompt or "", ai_config=ai_config)
    await ScriptService(db).update_script(script_id, ScriptUpdate(content=content, status="generated"))
    return ApiResponse(data=content)
