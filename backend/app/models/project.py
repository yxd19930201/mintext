from typing import Optional
from sqlalchemy import String, Text, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    genre: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    synopsis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_episodes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ai_config_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ai_configs.id"), nullable=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    owner: Mapped["User"] = relationship("User", back_populates="projects")
    characters: Mapped[list["Character"]] = relationship("Character", back_populates="project", cascade="all, delete-orphan")
    episodes: Mapped[list["Episode"]] = relationship("Episode", back_populates="project", cascade="all, delete-orphan")
