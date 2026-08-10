from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class AIConfigCreate(BaseModel):
    name: str
    base_url: str
    api_key: str
    model: str
    is_default: bool = False
    input_price_cny: float = 0
    output_price_cny: float = 0


class AIConfigUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    is_default: Optional[bool] = None
    input_price_cny: Optional[float] = None
    output_price_cny: Optional[float] = None


class AIConfigRead(BaseModel):
    id: int
    name: str
    base_url: str
    api_key: str
    model: str
    is_default: bool
    input_price_cny: float = 0
    output_price_cny: float = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
