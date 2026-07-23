from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import init_db
from app.routers.health import router as health_router
from app.routers.v1.router import router as v1_router
from app.services import license_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    debug=settings.DEBUG,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_license(request, call_next):
    path = request.url.path
    allowed = path == "/health" or path.startswith("/api/v1/license/")
    if not allowed and path.startswith("/api/") and not license_service.status()["activated"]:
        return JSONResponse(status_code=403, content={"detail": "LICENSE_REQUIRED:软件尚未激活"})
    return await call_next(request)


app.include_router(health_router)
app.include_router(v1_router, prefix="/api/v1")
