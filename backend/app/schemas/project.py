from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class ProjectCreate(BaseModel):
    title: str
    description: Optional[str] = None
    genre: Optional[str] = None
    synopsis: Optional[str] = None
    total_episodes: Optional[int] = None
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    genre: Optional[str] = None
    synopsis: Optional[str] = None
    outline: Optional[str] = None
    total_episodes: Optional[int] = None
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


class ProjectRead(BaseModel):
    id: int
    title: str
    description: Optional[str]
    genre: Optional[str]
    owner_id: int
    synopsis: Optional[str]
    outline: Optional[str]
    total_episodes: Optional[int]
    ai_config_id: Optional[int]
    system_prompt: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
