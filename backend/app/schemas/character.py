from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class CharacterCreate(BaseModel):
    name: str
    role: Optional[str] = None
    description: Optional[str] = None


class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    description: Optional[str] = None


class CharacterRead(BaseModel):
    id: int
    name: str
    role: Optional[str]
    description: Optional[str]
    project_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
