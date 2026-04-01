from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class ScriptCreate(BaseModel):
    content: Optional[str] = None
    ai_prompt: Optional[str] = None


class ScriptUpdate(BaseModel):
    content: Optional[str] = None
    ai_prompt: Optional[str] = None
    status: Optional[str] = None


class ScriptRead(BaseModel):
    id: int
    version: int
    status: str
    content: Optional[str]
    ai_prompt: Optional[str]
    episode_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
