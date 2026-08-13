from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.browser_job import BrowserJob


_extension_state: dict = {"connected": False, "last_seen_at": None}
_submission_locks: dict[str, asyncio.Lock] = {}


def mark_extension_seen(metadata: dict | None = None, **identity) -> dict:
    _extension_state.update({
        "connected": True,
        "last_seen_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or _extension_state.get("metadata") or {},
        **{key: value for key, value in identity.items() if value is not None},
    })
    return extension_state()


def extension_state() -> dict:
    state = dict(_extension_state)
    last_seen = state.get("last_seen_at")
    if last_seen:
        seen = datetime.fromisoformat(last_seen)
        state["connected"] = (datetime.now(timezone.utc) - seen).total_seconds() < 150
    else:
        state["connected"] = False
    return state


def extension_is_connected() -> bool:
    return bool(extension_state().get("connected"))


def mark_extension_disconnected() -> None:
    _extension_state.update({"connected": False, "last_seen_at": None})


async def _find_task(idempotency_key: str) -> BrowserJob | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BrowserJob)
            .where(
                BrowserJob.kind == "browser_ai",
                BrowserJob.idempotency_key == idempotency_key,
            )
            .order_by(BrowserJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def _create_or_resume_task(payload: dict) -> str:
    key = str(payload["idempotency_key"])
    lock = _submission_locks.setdefault(key, asyncio.Lock())
    async with lock:
        existing = await _find_task(key)
        if existing:
            if existing.status == "completed":
                return existing.id
            if existing.status in {"failed", "cancelled", "waiting_user", "adapter_outdated"}:
                async with AsyncSessionLocal() as db:
                    job = await db.get(BrowserJob, existing.id)
                    job.status = "queued"
                    job.error = None
                    job.result_json = "{}"
                    job.lease_token = None
                    job.leased_until = None
                    await db.commit()
            return existing.id

        async with AsyncSessionLocal() as db:
            job = BrowserJob(
                owner_id=1,
                kind="browser_ai",
                operation=str(payload.get("operation") or "text_generation"),
                idempotency_key=key,
                payload_json=json.dumps(payload, ensure_ascii=False),
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)
            return job.id


async def run_browser_ai_task(payload: dict, timeout_seconds: float = 780.0) -> dict:
    if not extension_is_connected():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BROWSER_EXTENSION_OFFLINE:青玉浏览器助手未连接。",
        )
    job_id = await _create_or_resume_task(payload)
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        async with AsyncSessionLocal() as db:
            job = await db.get(BrowserJob, job_id)
            if not job:
                raise HTTPException(status_code=502, detail="BROWSER_EXTENSION_JOB_LOST:浏览器任务不存在")
            if job.status == "completed":
                return job.result
            if job.status in {"failed", "cancelled", "adapter_outdated"}:
                raise HTTPException(
                    status_code=502,
                    detail=f"BROWSER_EXTENSION_AI_FAILED:{job.error or job.status}",
                )
            if job.status == "waiting_user":
                raise HTTPException(
                    status_code=409,
                    detail=f"BROWSER_EXTENSION_ACTION_REQUIRED:{job.error or '请在浏览器中完成登录或验证后重试'}",
                )
        await asyncio.sleep(1.0)
    raise HTTPException(
        status_code=504,
        detail="BROWSER_EXTENSION_AI_TIMEOUT:浏览器任务仍在执行，任务已保留；稍后重试会继续读取原结果。",
    )
