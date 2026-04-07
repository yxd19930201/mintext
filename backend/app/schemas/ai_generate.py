from typing import Optional
from pydantic import BaseModel


class GenerateOutlineRequest(BaseModel):
    project_id: int
    total_episodes: int = 10
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


class GenerateScriptRequest(BaseModel):
    extra_context: Optional[str] = None
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


class BatchGenerateRequest(BaseModel):
    project_id: Optional[int] = None
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None
    only_missing: bool = False


class GenerateNextEpisodeRequest(BaseModel):
    project_id: Optional[int] = None
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


class OutlineEpisode(BaseModel):
    episode_number: int
    title: str
    synopsis: str


class OutlineResult(BaseModel):
    total_episodes: int
    theme: str
    episodes: list[OutlineEpisode]
