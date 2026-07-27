from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    from app.models.base import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all() does not add columns to an existing SQLite database.
        # Keep upgrades non-destructive by adding the Skill continuity fields
        # in place; user AI settings, novels and generated content are retained.
        def existing_novel_columns(sync_conn):
            return {column["name"] for column in inspect(sync_conn).get_columns("novels")}

        columns = await conn.run_sync(existing_novel_columns)
        additions = {
            "story_roadmap": "TEXT",
            "state_ledger": "TEXT",
            "canon_facts": "TEXT",
            "continuity_audits": "TEXT",
        }
        for name, sql_type in additions.items():
            if name not in columns:
                await conn.execute(text(f"ALTER TABLE novels ADD COLUMN {name} {sql_type}"))
