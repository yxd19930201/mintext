from sqlalchemy import String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class AIPromptPreset(Base, TimestampMixin):
    __tablename__ = "ai_prompt_presets"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_global: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
