from pydantic import BaseModel, Field


class LicenseActivateRequest(BaseModel):
    license_key: str = Field(..., min_length=40, max_length=4096)


class LicenseStatus(BaseModel):
    activated: bool
    machine_code: str
    license_id: str | None = None
    issued_at: str | None = None
    expires_at: str | None = None
    days_remaining: int | None = None
    message: str | None = None
