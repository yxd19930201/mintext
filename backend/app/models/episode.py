from typing import Optional
from sqlalchemy import String, Text, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin


class Episode(Base, TimestampMixin):
    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    synopsis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)

    project: Mapped["Project"] = relationship("Project", back_populates="episodes")
    scripts: Mapped[list["Script"]] = relationship("Script", back_populates="episode", cascade="all, delete-orphan")
