from fastapi import APIRouter, HTTPException, status as http_status

from app.schemas.common import ApiResponse
from app.schemas.license import LicenseActivateRequest, LicenseStatus
from app.services import license_service

router = APIRouter()


@router.get("/status", response_model=ApiResponse[LicenseStatus])
async def get_license_status():
    return ApiResponse(data=LicenseStatus(**license_service.status()))


@router.post("/activate", response_model=ApiResponse[LicenseStatus])
async def activate_license(req: LicenseActivateRequest):
    try:
        result = license_service.activate(req.license_key)
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc) or "激活失败",
        ) from exc
    return ApiResponse(data=LicenseStatus(**result))
