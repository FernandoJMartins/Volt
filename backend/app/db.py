from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Colunas adicionadas depois do create_all inicial. Postgres aplica ADD COLUMN
# IF NOT EXISTS de forma idempotente — roda toda subida sem quebrar bancos antigos.
# Desde a Fase 4 o Alembic e' a fonte da verdade para MUDANCAS NOVAS (ver alembic/);
# estas linhas ficam como rede de seguranca idempotente para bancos ja criados.
_ADD_COLUMNS = (
    "ALTER TABLE x_accounts ADD COLUMN IF NOT EXISTS auth_method VARCHAR(16) DEFAULT 'browser'",
    "ALTER TABLE x_accounts ADD COLUMN IF NOT EXISTS session_state_encrypted TEXT DEFAULT ''",
    "ALTER TABLE x_accounts ADD COLUMN IF NOT EXISTS session_valid BOOLEAN DEFAULT false",
    "ALTER TABLE x_accounts ADD COLUMN IF NOT EXISTS session_updated_at TIMESTAMPTZ",
    "ALTER TABLE x_accounts ADD COLUMN IF NOT EXISTS user_agent VARCHAR(512) DEFAULT ''",
)

# Migracao de schema (idempotente): a UNIQUE global (user_id, x_user_id) explodia
# quando uma 2a conta browser nascia com x_user_id='' (placeholder pre-login).
# Troca por um indice unico PARCIAL, que so vale para x_user_id real.
# Ordem importa: drop da constraint (leva junto o indice de mesmo nome) antes do create.
_SCHEMA_MIGRATIONS = (
    "ALTER TABLE x_accounts DROP CONSTRAINT IF EXISTS uq_user_xaccount",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_xaccount"
    " ON x_accounts (user_id, x_user_id) WHERE x_user_id <> ''",
)

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Cria as tabelas (create_all idempotente).

    Para MUDANCAS de schema, use Alembic (`alembic revision --autogenerate` +
    `alembic upgrade head`) — o create_all so' cria o que nao existe e nao
    altera tabelas existentes.
    """
    from app import models  # noqa: F401  (registra os models no metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for statement in _ADD_COLUMNS:
            await conn.execute(text(statement))
        for statement in _SCHEMA_MIGRATIONS:
            await conn.execute(text(statement))
