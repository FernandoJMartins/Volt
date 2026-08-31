"""Scheduler: varre a fila a cada tick e despacha os jobs maduros para o worker."""

import asyncio
import logging
import time
from datetime import datetime, timezone

from arq import create_pool
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import RetweetJob, ScheduledPost, XAccount
from app.services.scheduling import distribute_slots  # noqa: F401  (reexport util)
from app.workers import _redis_settings

logging.basicConfig(
    level=logging.INFO, format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
)
log = logging.getLogger("scheduler")

TICK_SECONDS = 30

# Momento (monotonic) da ultima varredura de analytics. Em memoria de proposito:
# se o container reinicia, a varredura roda de novo — coleta a mais é inofensiva
# (upsert idempotente), coleta a menos é o que a periodicidade corrige.
_last_analytics_sweep = 0.0


async def sweep_analytics(pool) -> None:
    """A cada ANALYTICS_SWEEP_SECONDS, enfileira a coleta de engajamento para
    cada conta browser conectada. Uma navegacao por conta por varredura."""
    global _last_analytics_sweep
    now = time.monotonic()
    if now - _last_analytics_sweep < settings.ANALYTICS_SWEEP_SECONDS:
        return
    _last_analytics_sweep = now

    async with SessionLocal() as db:
        ids = (
            await db.execute(
                select(XAccount.id).where(
                    XAccount.is_active.is_(True),
                    XAccount.auth_method == "browser",
                    XAccount.session_valid.is_(True),
                )
            )
        ).scalars().all()
    for account_id in ids:
        await pool.enqueue_job("collect_post_stats", account_id)
    if ids:
        log.info("Varredura de analytics: %d conta(s)", len(ids))


async def dispatch_due() -> None:
    now = datetime.now(timezone.utc)
    pool = await create_pool(_redis_settings())
    try:
        async with SessionLocal() as db:
            posts = (
                await db.execute(
                    select(ScheduledPost.id).where(
                        ScheduledPost.status == "queued", ScheduledPost.scheduled_at <= now
                    )
                )
            ).scalars().all()
            for post_id in posts:
                await pool.enqueue_job("publish_scheduled", post_id)

            retweets = (
                await db.execute(
                    select(RetweetJob.id).where(
                        RetweetJob.status == "queued", RetweetJob.scheduled_at <= now
                    )
                )
            ).scalars().all()
            for job_id in retweets:
                await pool.enqueue_job("run_retweet", job_id)

        await sweep_analytics(pool)

        if posts or retweets:
            log.info("Despachados %d posts e %d retweets", len(posts), len(retweets))
    finally:
        await pool.aclose()


async def main() -> None:
    log.info("Scheduler iniciado (tick=%ds)", TICK_SECONDS)
    while True:
        try:
            await dispatch_due()
        except Exception:  # noqa: BLE001
            log.exception("Erro no tick do scheduler")
        await asyncio.sleep(TICK_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
