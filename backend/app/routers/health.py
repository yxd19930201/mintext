from fastapi import APIRouter
from datetime import datetime, timezone
import sys, os

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/health/env")
async def health_env():
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("https://api.deepseek.com")
            reachable = r.status_code < 500
    except Exception as e:
        reachable = False
        reach_err = str(e)
    return {
        "python": sys.executable,
        "httpx": httpx.__version__,
        "deepseek_reachable": reachable,
        "reach_err": locals().get("reach_err"),
        "http_proxy": os.environ.get("HTTP_PROXY"),
        "https_proxy": os.environ.get("HTTPS_PROXY"),
    }
