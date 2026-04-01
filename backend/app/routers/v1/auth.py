from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.auth_service import AuthService
from app.schemas.user import UserCreate, UserRead, TokenResponse
from app.schemas.common import ApiResponse

router = APIRouter()


@router.post("/register", response_model=ApiResponse[UserRead])
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)):
    user = await AuthService(db).register(data)
    return ApiResponse(data=UserRead.model_validate(user))


@router.post("/login", response_model=ApiResponse[TokenResponse])
async def login(data: UserCreate, db: AsyncSession = Depends(get_db)):
    token = await AuthService(db).login(data.email, data.password)
    return ApiResponse(data=token)
