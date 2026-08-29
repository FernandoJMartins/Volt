from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Colunas adicionadas depois do create_all inicial. Postgres aplica ADD COLUMN
# IF NOT EXISTS de forma idempotente — roda toda subida sem quebrar bancos antigos.
# Substitui um Alembic completo enquanto o projeto esta em MVP.
_ADD_COLUMNS = (
    "ALTER TABLE x_accounts ADD COLUMN IF NOT EXISTS auth_method VARCHAR(16) DEFAULT 'browser'",
    "ALTER TABLE x_accounts ADD COLUMN IF NOT EXISTS session_state_encrypted TEXT DEFAULT ''",
    "ALTER TABLE x_accounts ADD COLUMN IF NOT EXISTS session_valid BOOLEAN DEFAULT false",
    "ALTER TABLE x_accounts ADD COLUMN IF NOT EXISTS session_updated_at TIMESTAMPTZ",
    "ALTER TABLE x_accounts ADD COLUMN IF NOT EXISTS user_agent VARCHAR(512) DEFAULT ''",
)

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Cria as tabelas. MVP usa create_all; Alembic entra na Fase 4."""
    from app import models  # noqa: F401  (registra os models no metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for statement in _ADD_COLUMNS:
            await conn.execute(text(statement))
