from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.manuscript_report import ManuscriptReport
from app.repositories.base import BaseRepository


class ManuscriptReportRepository(BaseRepository[ManuscriptReport]):
    def __init__(self, db: AsyncSession):
        super().__init__(ManuscriptReport, db)

    async def list_by_owner(self, owner_id: int, limit: int = 50) -> list[ManuscriptReport]:
        result = await self.db.execute(
            select(ManuscriptReport)
            .where(ManuscriptReport.owner_id == owner_id)
            .order_by(ManuscriptReport.created_at.desc(), ManuscriptReport.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_owner(self, report_id: int, owner_id: int) -> ManuscriptReport | None:
        result = await self.db.execute(
            select(ManuscriptReport).where(
                ManuscriptReport.id == report_id,
                ManuscriptReport.owner_id == owner_id,
            )
        )
        return result.scalar_one_or_none()

