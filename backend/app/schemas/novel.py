from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class NovelBase(BaseModel):
    title: str = Field(..., max_length=200)
    genre: Optional[str] = Field(None, max_length=50)
    synopsis: str
    total_chapters: Optional[int] = None
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


class NovelCreate(NovelBase):
    pass


class NovelUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    genre: Optional[str] = Field(None, max_length=50)
    synopsis: Optional[str] = None
    outline: Optional[str] = None
    total_chapters: Optional[int] = None
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


class NovelRead(NovelBase):
    id: int
    outline: Optional[str] = None
    owner_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
