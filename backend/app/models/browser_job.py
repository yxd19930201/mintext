import json
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.models.base import Base, TimestampMixin


class BrowserJob(Base, TimestampMixin):
    """Durable work item claimed by the local Qingyu browser extension."""

    __tablename__ = "browser_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = Column(Integer, nullable=False, default=1, index=True)
    kind = Column(String(32), nullable=False, default="fanqie_publish", index=True)
    operation = Column(String(32), nullable=False, index=True)
    payload_json = Column(Text, nullable=False, default="{}")
    status = Column(String(32), nullable=False, default="queued", index=True)
    result_json = Column(Text, nullable=False, default="{}")
    error = Column(Text, nullable=True)
    lease_token = Column(String(64), nullable=True)
    leased_until = Column(DateTime(timezone=True), nullable=True)
    last_progress_at = Column(DateTime(timezone=True), nullable=True)

    @property
    def payload(self):
        try:
            return json.loads(self.payload_json or "{}")
        except (TypeError, ValueError):
            return {}

    @property
    def result(self):
        try:
            return json.loads(self.result_json or "{}")
        except (TypeError, ValueError):
            return {}

    def renew_lease(self, seconds: int = 90):
        from datetime import timedelta

        self.lease_token = self.lease_token or secrets.token_urlsafe(24)
        self.leased_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        self.last_progress_at = datetime.now(timezone.utc)
