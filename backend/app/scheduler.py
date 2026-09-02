"""Scheduler: varre a fila a cada tick e despacha os jobs maduros para o worker."""

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta, timezone

from arq import create_pool
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Account, MonitoredAccount, RetweetJob, ScheduledPost
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
_last_autopilot_sweep = 0.0
_last_collection_sweep = 0.0


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
                select(Account.id).where(
                    Account.is_active.is_(True),
                    Account.auth_method == "browser",
                    Account.session_valid.is_(True),
                )
            )
        ).scalars().all()
    for account_id in ids:
        await pool.enqueue_job("collect_post_stats", account_id)
    if ids:
        log.info("Varredura de analytics: %d conta(s)", len(ids))


async def sweep_autopilot(pool) -> None:
    """A cada AUTOPILOT_SWEEP_SECONDS, enfileira UMA varredura do piloto
    automatico no worker (nunca roda inline aqui — pode chamar IA e levar
    minutos, o que travaria o despacho de posts due neste mesmo loop)."""
    global _last_autopilot_sweep
    now = time.monotonic()
    if now - _last_autopilot_sweep < settings.AUTOPILOT_SWEEP_SECONDS:
        return
    _last_autopilot_sweep = now
    await pool.enqueue_job("autopilot_sweep")


async def sweep_collection(pool) -> None:
    """A cada COLLECTION_SWEEP_SECONDS, enfileira a coleta das fontes monitoradas
    (X e Threads) que estao devidas — sem precisar clicar em "Coletar".

    Cadencia por fonte e' ~1x/dia mas com jitter (ver COLLECTION_INTERVAL_MIN/
    MAX_HOURS e workers.collect_account): de proposito nunca cai num horario
    redondo fixo, pra nao parecer um robo previsivel.
    """
    global _last_collection_sweep
    now_mono = time.monotonic()
    if now_mono - _last_collection_sweep < settings.COLLECTION_SWEEP_SECONDS:
        return
    _last_collection_sweep = now_mono

    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        due = (
            await db.execute(
                select(MonitoredAccount).where(
                    MonitoredAccount.is_active.is_(True),
                    (MonitoredAccount.next_collect_at.is_(None))
                    | (MonitoredAccount.next_collect_at <= now),
                )
            )
        ).scalars().all()
        for account in due:
            # Marca otimisticamente antes de enfileirar — evita reenfileirar a
            # mesma fonte na proxima varredura enquanto o job ainda roda/falha.
            # collect_account recalcula com jitter de verdade ao terminar.
            account.next_collect_at = now + timedelta(
                hours=random.uniform(
                    settings.COLLECTION_INTERVAL_MIN_HOURS, settings.COLLECTION_INTERVAL_MAX_HOURS
                )
            )
        await db.commit()

    # Espalha os disparos no tempo — contas da mesma plataforma competem pelo
    # lock da conta-leitora (browser.py); mandar tudo junto so' empilha jobs
    # esperando o lock ate estourar o timeout. Tambem fica mais "gente" que
    # "robo despejando tudo no mesmo segundo".
    defer = 0
    for account in due:
        await pool.enqueue_job("collect_account", account.id, _defer_by=defer)
        defer += random.randint(60, 180)
    if due:
        log.info("Varredura de coleta: %d fonte(s)", len(due))


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
        await sweep_autopilot(pool)
        await sweep_collection(pool)

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
