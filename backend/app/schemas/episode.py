from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class EpisodeCreate(BaseModel):
    title: str
    episode_number: int
    synopsis: Optional[str] = None


class EpisodeUpdate(BaseModel):
    title: Optional[str] = None
    episode_number: Optional[int] = None
    synopsis: Optional[str] = None


class EpisodeRead(BaseModel):
    id: int
    title: str
    episode_number: int
    synopsis: Optional[str]
    project_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
