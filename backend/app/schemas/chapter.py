from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class ChapterBase(BaseModel):
    title: str = Field(..., max_length=200)
    chapter_number: int
    synopsis: Optional[str] = None


class ChapterCreate(ChapterBase):
    pass


class ChapterUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    synopsis: Optional[str] = None


class ChapterRead(ChapterBase):
    id: int
    novel_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
