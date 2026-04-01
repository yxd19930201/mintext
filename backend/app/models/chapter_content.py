from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.models.base import Base


class ChapterContent(Base):
    __tablename__ = "chapter_contents"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=True)
    word_count = Column(Integer, default=0)
    status = Column(String(20), default="draft")  # draft/generated/reviewed
    version = Column(Integer, default=1)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    chapter = relationship("Chapter", back_populates="contents")
