"""
Dependencies — injected into route handlers.

Development mode: get_current_user_id always returns 1 (no JWT required).
Production mode: uncomment the JWT block and comment out the dev stub.
"""
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db


async def get_current_user_id(
    # --- Production: uncomment below ---
    # token: str = Depends(OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")),
) -> int:
    # --- Development stub ---
    return 1
    # --- Production: replace stub with ---
    # from app.services.auth_service import decode_token
    # return decode_token(token)
