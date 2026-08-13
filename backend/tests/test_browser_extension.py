import asyncio
from datetime import datetime, timedelta, timezone
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.browser_job import BrowserJob
from app.services.browser_extension_service import mark_extension_disconnected


def test_local_extension_connect_and_job_lifecycle(monkeypatch):
    monkeypatch.setenv("MINITEXT_LICENSE_BYPASS", "1")
    asyncio.run(_exercise_lifecycle())


async def _exercise_lifecycle():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            connected = await client.post("/api/v1/browser-extension/connect", json={})
            assert connected.status_code == 200
            assert connected.json()["data"]["workspace_id"] == "mintext-local"

            status = await client.get("/api/v1/browser-extension/status")
            assert status.status_code == 200
            assert status.json()["data"]["connected"] is True

            created = await client.post(
                "/api/v1/browser-extension/jobs",
                json={"operation": "CHECK_SESSION", "payload": {}},
            )
            assert created.status_code == 200
            job_id = created.json()["data"]["id"]

            claimed = await client.post("/api/v1/browser-extension/jobs/claim?wait_seconds=0")
            assert claimed.status_code == 200
            job = claimed.json()["data"]
            assert job["id"] == job_id
            assert job["status"] == "leased"
            assert job["lease_token"]

            started = await client.post(
                f"/api/v1/browser-extension/jobs/{job_id}/events",
                json={
                    "event_type": "STARTED",
                    "payload": {},
                    "lease_token": job["lease_token"],
                },
            )
            assert started.json()["data"]["status"] == "running"

            async with session_factory() as session:
                stalled = await session.get(BrowserJob, job_id)
                stalled.leased_until = datetime.now(timezone.utc) - timedelta(seconds=1)
                await session.commit()

            reclaimed = await client.post("/api/v1/browser-extension/jobs/claim?wait_seconds=0")
            assert reclaimed.status_code == 200
            job = reclaimed.json()["data"]
            assert job["id"] == job_id
            assert job["status"] == "leased"

            completed = await client.post(
                f"/api/v1/browser-extension/jobs/{job_id}/complete",
                json={
                    "status": "processed",
                    "result": {"authenticated": True},
                    "lease_token": job["lease_token"],
                },
            )
            assert completed.status_code == 200
            assert completed.json()["data"]["status"] == "completed"
            assert completed.json()["data"]["result"]["authenticated"] is True

            disconnected = await client.post("/api/v1/browser-extension/disconnect")
            assert disconnected.status_code == 200
            status = await client.get("/api/v1/browser-extension/status")
            assert status.json()["data"]["connected"] is False
    finally:
        mark_extension_disconnected()
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
