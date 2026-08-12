from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from app.schemas.generation_mode import GenerationModeOptions


InspectionType = Literal["quality", "ai_trace"]


class ManuscriptDocument(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=20, max_length=2_000_000)
    chapter_number: int | None = Field(None, ge=1)


class ManuscriptInspectionRequest(GenerationModeOptions):
    inspection_type: InspectionType
    novel_id: int | None = None
    source_name: str | None = Field(None, max_length=255)
    source_text: str | None = Field(None, max_length=4_000_000)
    source_documents: list[ManuscriptDocument] | None = Field(None, min_length=1, max_length=500)
    ai_config_id: int | None = None

    @model_validator(mode="after")
    def validate_source(self):
        has_novel = self.novel_id is not None
        has_text = bool((self.source_text or "").strip())
        has_documents = bool(self.source_documents)
        if sum((has_novel, has_text, has_documents)) != 1:
            raise ValueError("请选择一部书架小说、一个文本文件或一个章节文件夹（三选一）")
        if has_text and len((self.source_text or "").strip()) < 200:
            raise ValueError("导入文本至少需要 200 个字符")
        if has_documents:
            total = sum(len(document.content) for document in self.source_documents or [])
            if total < 200:
                raise ValueError("章节文件夹正文总量至少需要 200 个字符")
            if total > 20_000_000:
                raise ValueError("章节文件夹正文总量不能超过 2000 万字符")
        return self


class ManuscriptReportRead(BaseModel):
    id: int
    inspection_type: InspectionType
    source_name: str
    novel_id: int | None = None
    word_count: int
    report: dict[str, Any]
    created_at: datetime


class ManuscriptReportSummary(BaseModel):
    id: int
    inspection_type: InspectionType
    source_name: str
    novel_id: int | None = None
    word_count: int
    overall_score: float
    verdict: str
    status: str = "completed"
    completed_chapters: int = 0
    total_chapters: int = 0
    created_at: datetime
