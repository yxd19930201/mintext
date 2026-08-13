from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


BrowserOperation = Literal[
    "CHECK_SESSION", "LIST_BOOKS", "CREATE_BOOK", "LIST_CHAPTERS",
    "PUBLISH_CHAPTER", "OVERWRITE_CHAPTER", "VERIFY_CHAPTER", "CANCEL_BATCH",
]


class BrowserJobCreate(BaseModel):
    operation: BrowserOperation
    payload: dict[str, Any] = Field(default_factory=dict)
    kind: str = "fanqie_publish"


class PublishChapterCreate(BaseModel):
    chapter_id: int
    platform_book_id: str = Field(min_length=1, max_length=100)
    overwrite: bool = False
    platform_chapter_id: str | None = None
    scheduled_at: datetime | None = None


class BrowserJobComplete(BaseModel):
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    lease_token: str | None = None


class BrowserJobEvent(BaseModel):
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    lease_token: str | None = None


class BrowserConnect(BaseModel):
    device_id: str | None = None
    browser: str | None = None
    extension_version: str | None = None
    display_name: str | None = None
