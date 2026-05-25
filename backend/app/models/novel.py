from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.models.base import Base


class Novel(Base):
    __tablename__ = "novels"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    genre = Column(String(50), nullable=True)
    synopsis = Column(Text, nullable=False)
    outline = Column(Text, nullable=True)  # JSON format
    knowledge_graph = Column(Text, nullable=True)  # JSON: {characters:[...], events:[...]}
    total_chapters = Column(Integer, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ai_config_id = Column(Integer, ForeignKey("ai_configs.id", ondelete="SET NULL"), nullable=True)
    system_prompt = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    owner = relationship("User", back_populates="novels")
    ai_config = relationship("AIConfig")
    chapters = relationship("Chapter", back_populates="novel", cascade="all, delete-orphan")
