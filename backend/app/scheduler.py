"""Scheduler: varre a fila a cada tick e despacha os jobs maduros para o worker."""

import asyncio
import logging
from datetime import datetime, timezone

from arq import create_pool
from sqlalchemy import select

from app.db import SessionLocal
from app.models import RetweetJob, ScheduledPost
from app.services.scheduling import distribute_slots  # noqa: F401  (reexport util)
from app.workers import _redis_settings

logging.basicConfig(
    level=logging.INFO, format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
)
log = logging.getLogger("scheduler")

TICK_SECONDS = 30


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
