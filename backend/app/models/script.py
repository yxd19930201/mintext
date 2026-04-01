from typing import Optional
from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin


class Script(Base, TimestampMixin):
    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), nullable=False)

    episode: Mapped["Episode"] = relationship("Episode", back_populates="scripts")
