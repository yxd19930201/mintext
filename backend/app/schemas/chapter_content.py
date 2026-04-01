from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ChapterContentBase(BaseModel):
    content: Optional[str] = None
    status: str = "draft"


class ChapterContentCreate(ChapterContentBase):
    pass


class ChapterContentUpdate(BaseModel):
    content: Optional[str] = None
    status: Optional[str] = None


class ChapterContentRead(ChapterContentBase):
    id: int
    word_count: int
    version: int
    chapter_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
