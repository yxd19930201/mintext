import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.models.browser_job import BrowserJob
from app.repositories.chapter_content_repo import ChapterContentRepository
from app.repositories.chapter_repo import ChapterRepository
from app.schemas.browser_extension import (
    BrowserJobComplete,
    BrowserJobCreate,
    BrowserJobEvent,
    BrowserConnect,
    PublishChapterCreate,
)
from app.schemas.common import ApiResponse


router = APIRouter()
_extension_state: dict = {"connected": False, "last_seen_at": None}


def _job_read(job: BrowserJob) -> dict:
    return {
        "id": job.id,
        "kind": job.kind,
        "operation": job.operation,
        "payload": job.payload,
        "status": job.status,
        "result": job.result,
        "error": job.error,
        "lease_token": job.lease_token,
        "leased_until": job.leased_until.isoformat() if job.leased_until else None,
        "last_progress_at": job.last_progress_at.isoformat() if job.last_progress_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


@router.post("/connect", response_model=ApiResponse[dict])
async def connect_extension(req: BrowserConnect):
    _extension_state.update({
        "connected": True,
        "last_seen_at": datetime.now(timezone.utc).isoformat(),
        "device_id": req.device_id or "local-browser",
        "browser": req.browser,
        "extension_version": req.extension_version,
        "display_name": req.display_name or "青玉浏览器助手",
    })
    # Localhost-only transport: the token is a compatibility marker, not a cloud credential.
    return ApiResponse(data={
        "access_token": "mintext-local-extension",
        "refresh_token": "mintext-local-extension",
        "device_id": req.device_id or "local-browser",
        "workspace_id": "mintext-local",
    })


@router.post("/jobs", response_model=ApiResponse[dict])
async def create_job(
    req: BrowserJobCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    job = BrowserJob(
        owner_id=user_id,
        kind=req.kind,
        operation=req.operation,
        payload_json=json.dumps(req.payload, ensure_ascii=False),
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return ApiResponse(data=_job_read(job))


@router.post("/publish-chapter", response_model=ApiResponse[dict])
async def publish_chapter(
    req: PublishChapterCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    chapter = await ChapterRepository(db).get(req.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    content = await ChapterContentRepository(db).get_latest(req.chapter_id)
    body = str(getattr(content, "content", "") or "").strip()
    if not body:
        raise HTTPException(status_code=409, detail="章节尚无可发布的正式正文")
    payload = {
        "chapter_id": chapter.id,
        "novel_id": chapter.novel_id,
        "platform_book_id": req.platform_book_id,
        "platform_chapter_id": req.platform_chapter_id,
        "chapter_no": chapter.chapter_number,
        "title": chapter.title,
        "body": body,
        "scheduled_at": req.scheduled_at.isoformat() if req.scheduled_at else None,
    }
    job = BrowserJob(
        owner_id=user_id,
        operation="OVERWRITE_CHAPTER" if req.overwrite else "PUBLISH_CHAPTER",
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return ApiResponse(data=_job_read(job))


@router.get("/jobs", response_model=ApiResponse[list[dict]])
async def list_jobs(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    result = await db.execute(
        select(BrowserJob)
        .where(BrowserJob.owner_id == user_id)
        .order_by(BrowserJob.created_at.desc())
        .limit(limit)
    )
    return ApiResponse(data=[_job_read(job) for job in result.scalars().all()])


@router.post("/heartbeat", response_model=ApiResponse[dict])
async def heartbeat(metadata: dict | None = None):
    _extension_state.update({
        "connected": True,
        "last_seen_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    })
    return ApiResponse(data={"accepted": True, "server_time": _extension_state["last_seen_at"]})


@router.get("/status", response_model=ApiResponse[dict])
async def extension_status():
    state = dict(_extension_state)
    last_seen = state.get("last_seen_at")
    if last_seen:
        seen = datetime.fromisoformat(last_seen)
        state["connected"] = (datetime.now(timezone.utc) - seen).total_seconds() < 150
    return ApiResponse(data=state)


@router.post("/jobs/claim", response_model=ApiResponse[dict])
async def claim_job(
    wait_seconds: int = Query(0, ge=0, le=25),
    db: AsyncSession = Depends(get_db),
):
    del wait_seconds  # Desktop polling stays short; the extension's alarm provides backoff.
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(BrowserJob)
        .where(or_(
            BrowserJob.status == "queued",
            (BrowserJob.status == "leased") & (BrowserJob.leased_until < now),
        ))
        .order_by(BrowserJob.created_at.asc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if not job:
        return ApiResponse(data={"job": None})
    job.status = "leased"
    job.renew_lease()
    await db.flush()
    await db.refresh(job)
    return ApiResponse(data=_job_read(job))


@router.post("/jobs/{job_id}/events", response_model=ApiResponse[dict])
async def job_event(job_id: str, req: BrowserJobEvent, db: AsyncSession = Depends(get_db)):
    job = await db.get(BrowserJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="浏览器任务不存在")
    if job.lease_token and req.lease_token != job.lease_token:
        raise HTTPException(status_code=409, detail="浏览器任务租约已变化")
    if req.event_type in {"STARTED", "LEASE_RENEWED", "PROGRESS"}:
        job.status = "running"
        job.renew_lease()
    elif req.event_type == "RATE_LIMITED":
        job.status = "waiting_user"
        job.error = str(req.payload.get("error") or "平台限流")
    await db.flush()
    await db.refresh(job)
    return ApiResponse(data=_job_read(job))


@router.post("/jobs/{job_id}/complete", response_model=ApiResponse[dict])
async def complete_job(job_id: str, req: BrowserJobComplete, db: AsyncSession = Depends(get_db)):
    job = await db.get(BrowserJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="浏览器任务不存在")
    if job.lease_token and req.lease_token != job.lease_token:
        raise HTTPException(status_code=409, detail="浏览器任务租约已变化")
    status_map = {"processed": "completed", "verified": "completed"}
    job.status = status_map.get(req.status, req.status)
    job.result_json = json.dumps(req.result, ensure_ascii=False)
    job.error = req.error
    job.last_progress_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(job)
    return ApiResponse(data=_job_read(job))
