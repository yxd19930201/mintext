from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class AIPromptPresetCreate(BaseModel):
    name: str
    content: str
    is_global: bool = True


class AIPromptPresetUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    is_global: Optional[bool] = None


class AIPromptPresetRead(BaseModel):
    id: int
    name: str
    content: str
    is_global: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
