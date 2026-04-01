from pydantic import BaseModel, Field
from typing import Optional


class NovelToScriptRequest(BaseModel):
    novel_text: str = Field(..., min_length=1, max_length=10000)
    target_episodes: int = Field(default=5, ge=1, le=20)
    style: Optional[str] = Field(None, max_length=100)
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


class ScriptToVideoRequest(BaseModel):
    script_text: str = Field(..., min_length=1)
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


class ConversionEpisode(BaseModel):
    episode_number: int
    title: str
    script: str
    duration_estimate: str  # e.g., "3-5分钟"


class NovelToScriptResult(BaseModel):
    total_episodes: int
    episodes: list[ConversionEpisode]


class VideoScriptScene(BaseModel):
    scene_number: int
    description: str
    duration: str
    camera_angle: str
    lighting: str


class ScriptToVideoResult(BaseModel):
    scenes: list[VideoScriptScene]
    total_duration: str
