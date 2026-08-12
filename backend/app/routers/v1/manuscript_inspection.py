from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.common import ApiResponse
from app.schemas.manuscript_inspection import (
    ManuscriptInspectionRequest,
    ManuscriptReportRead,
    ManuscriptReportSummary,
)
from app.services.manuscript_inspection_service import ManuscriptInspectionService


router = APIRouter()


@router.post("/inspect", response_model=ApiResponse[ManuscriptReportRead])
async def inspect_manuscript(
    req: ManuscriptInspectionRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    return ApiResponse(data=await ManuscriptInspectionService(db).inspect(req, user_id))


@router.get("/reports", response_model=ApiResponse[list[ManuscriptReportSummary]])
async def list_manuscript_reports(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    return ApiResponse(data=await ManuscriptInspectionService(db).list_reports(user_id))


@router.get("/reports/{report_id}", response_model=ApiResponse[ManuscriptReportRead])
async def get_manuscript_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    return ApiResponse(data=await ManuscriptInspectionService(db).get_report(report_id, user_id))


@router.delete("/reports/{report_id}", status_code=204)
async def delete_manuscript_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    await ManuscriptInspectionService(db).delete_report(report_id, user_id)

