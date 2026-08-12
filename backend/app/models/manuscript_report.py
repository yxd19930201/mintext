from sqlalchemy import Column, Integer, String, Text, ForeignKey

from app.models.base import Base, TimestampMixin


class ManuscriptReport(Base, TimestampMixin):
    __tablename__ = "manuscript_reports"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=True, index=True)
    inspection_type = Column(String(32), nullable=False, index=True)
    source_name = Column(String(255), nullable=False)
    word_count = Column(Integer, nullable=False, default=0)
    report_json = Column(Text, nullable=False)

