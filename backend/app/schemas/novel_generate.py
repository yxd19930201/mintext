from pydantic import BaseModel, Field
from typing import Optional, List


# Request schemas
class GenerateNovelOutlineRequest(BaseModel):
    novel_id: int
    total_chapters: int = Field(..., ge=1, le=500)
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


class GenerateChapterRequest(BaseModel):
    extra_context: Optional[str] = None
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


class BatchGenerateChaptersRequest(BaseModel):
    only_missing: bool = False
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


class GenerateNextChapterRequest(BaseModel):
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


# Response schemas
class ChapterOutlineItem(BaseModel):
    chapter_number: int
    title: str
    synopsis: str


class OutlineResult(BaseModel):
    total_chapters: int
    theme: str
    chapters: List[ChapterOutlineItem]


class GenerateChapterResult(BaseModel):
    chapter_id: int
    content_id: int
    content: str
    word_count: int


class BatchGenerateResult(BaseModel):
    total: int
    succeeded: int
    failed: int
    errors: List[dict]


class GenerateNextChapterResult(BaseModel):
    chapter_id: int
    chapter_number: int
    title: str
    synopsis: str
    content_id: int
