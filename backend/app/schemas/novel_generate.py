import json
import re
from typing import Any, Literal, Optional, List

from pydantic import BaseModel, Field, field_validator
from app.schemas.generation_mode import GenerationModeOptions


# Request schemas
class GenerateNovelOutlineRequest(GenerationModeOptions):
    novel_id: int
    total_chapters: int = Field(..., ge=1, le=200)
    start_chapter: int = Field(1, ge=1)
    end_chapter: Optional[int] = None  # inclusive; defaults to total_chapters
    theme: Optional[str] = None        # pass back theme from first batch
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


class GenerateChapterRequest(GenerationModeOptions):
    extra_context: Optional[str] = None
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None
    regenerate: bool = False
    restart_failed_generation: bool = False


class BatchGenerateChaptersRequest(GenerationModeOptions):
    only_missing: bool = False
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


class GenerateNextChapterRequest(GenerationModeOptions):
    ai_config_id: Optional[int] = None
    system_prompt: Optional[str] = None


# Response schemas
class ChapterOutlineItem(BaseModel):
    chapter_number: int
    title: str
    synopsis: str
    stage_id: Optional[str] = None
    before_state: dict = Field(default_factory=dict)
    after_state: dict = Field(default_factory=dict)
    irreversible_facts: List[str] = Field(default_factory=list)
    transition: Optional[str] = None
    speech_constraints: List[str] = Field(default_factory=list)
    relationship_changes: List[dict] = Field(default_factory=list)
    address_changes: List[dict] = Field(default_factory=list)

    @field_validator("chapter_number", mode="before")
    @classmethod
    def normalize_chapter_number(cls, value: Any) -> int:
        if isinstance(value, bool):
            raise ValueError("chapter_number cannot be boolean")
        if isinstance(value, (int, float)):
            return int(value)
        match = re.search(r"\d+", str(value or ""))
        if not match:
            raise ValueError("chapter_number must contain a number")
        return int(match.group())

    @field_validator("title", "synopsis", mode="before")
    @classmethod
    def normalize_required_text(cls, value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("summary", "content", "text", "description", "value"):
                if value.get(key):
                    return str(value[key]).strip()
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, list):
            return "；".join(str(item) for item in value if item is not None).strip()
        return str(value or "").strip()

    @field_validator("stage_id", "transition", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = cls.normalize_required_text(value)
        return text or None

    @field_validator("before_state", "after_state", mode="before")
    @classmethod
    def normalize_state(cls, value: Any) -> dict:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return {"items": value}
        return {"summary": str(value).strip()}

    @field_validator("irreversible_facts", "speech_constraints", mode="before")
    @classmethod
    def normalize_facts(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, dict):
            return [f"{key}：{item}" for key, item in value.items()]
        items = value if isinstance(value, list) else [value]
        normalized: list[str] = []
        for item in items:
            if item is None or item == "":
                continue
            if isinstance(item, str):
                normalized.append(item.strip())
            elif isinstance(item, dict):
                normalized.append(json.dumps(item, ensure_ascii=False))
            else:
                normalized.append(str(item))
        return normalized

    @field_validator("relationship_changes", "address_changes", mode="before")
    @classmethod
    def normalize_change_records(cls, value: Any) -> list[dict]:
        if value is None or value == "":
            return []
        items = value if isinstance(value, list) else [value]
        normalized: list[dict] = []
        for item in items:
            if isinstance(item, dict):
                normalized.append(item)
            elif item not in (None, ""):
                normalized.append({"description": str(item)})
        return normalized


class OutlineResult(BaseModel):
    total_chapters: int
    theme: str
    chapters: List[ChapterOutlineItem]
    is_partial: bool = False   # True when this is one batch of a multi-batch generation

    @field_validator("theme", mode="before")
    @classmethod
    def normalize_theme(cls, value: Any) -> str:
        return ChapterOutlineItem.normalize_required_text(value)

    @field_validator("chapters", mode="before")
    @classmethod
    def normalize_chapter_collection(cls, value: Any) -> list:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = value.get("chapters")
            if isinstance(nested, list):
                return nested
            if "chapter_number" in value:
                return [value]
            return list(value.values())
        return []


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
