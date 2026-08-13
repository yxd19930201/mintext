from fastapi import APIRouter
from app.routers.v1 import auth, projects, characters, episodes, scripts, ai, novels, chapters, novel_ai, conversion, license, manuscript_inspection, browser_extension

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(projects.router, prefix="/projects", tags=["projects"])
router.include_router(characters.router, prefix="/projects", tags=["characters"])
router.include_router(episodes.router, prefix="/projects", tags=["episodes"])
router.include_router(scripts.router, prefix="/episodes", tags=["scripts"])
router.include_router(ai.router, prefix="/ai", tags=["ai"])
router.include_router(novels.router, prefix="/novels", tags=["novels"])
router.include_router(chapters.router, prefix="/novels", tags=["chapters"])
router.include_router(novel_ai.router, prefix="/novel-ai", tags=["novel-ai"])
router.include_router(conversion.router, prefix="/conversion", tags=["conversion"])
router.include_router(license.router, prefix="/license", tags=["license"])
router.include_router(manuscript_inspection.router, prefix="/manuscript", tags=["manuscript-inspection"])
router.include_router(browser_extension.router, prefix="/browser-extension", tags=["browser-extension"])
