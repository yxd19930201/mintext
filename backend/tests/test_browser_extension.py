import asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_db
from app.main import app
from app.models.base import Base


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
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
