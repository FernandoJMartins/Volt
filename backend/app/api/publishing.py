"""Fila de publicacao, calendario e retweets escalonados entre contas proprias."""

import random
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import current_user
from app.db import get_db
from app.api.content import load_media_map
from app.models import AuditLog, ContentCandidate, PostStats, RetweetJob, ScheduledPost, User, XAccount
from app.services import analytics as an
from app.services.scheduling import distribute_slots, fit_window
from app.workers import enqueue

router = APIRouter(prefix="/api", tags=["publishing"])


class ScheduleIn(BaseModel):
    content_candidate_id: int
    scheduled_at: datetime | None = None  # None = publicar agora


class AutoScheduleIn(BaseModel):
    """Intervalo entre posts definido pelo usuario, em minutos.

    O X nao expoe agendamento nativo aqui — quem publica no horario é o nosso
    worker. O teto de 30 dias é regra nossa, para a fila nao virar um planejamento
    infinito que ninguem revisa.
    """

    x_account_id: int
    candidate_ids: list[int] = []
    start_in_minutes: int = Field(default=5, ge=1, le=1440)
    min_interval_minutes: int = Field(default=30, ge=1, le=1440)
    max_interval_minutes: int = Field(default=120, ge=1, le=1440)
    horizon_days: int = Field(default=30, ge=1, le=30)
    respect_window: bool = True
    # 'spread' = espacamento pelo intervalo escolhido; 'optimized' = horarios
    # guiados pelo engajamento historico da conta (Fase 5, analytics).
    strategy: str = Field(default="spread", pattern="^(spread|optimized)$")


class RescheduleIn(BaseModel):
    scheduled_at: datetime | None = None
    x_account_id: int | None = None


class RetweetIn(BaseModel):
    source_tweet_id: str = Field(min_length=1, max_length=64)
    target_account_ids: list[int] = Field(min_length=1)
    origin_x_account_id: int | None = None
    delay_min_minutes: int = Field(default=5, ge=5, le=120)
    delay_max_minutes: int = Field(default=120, ge=5, le=120)


# ---------- Fila / agendamento ----------


@router.get("/scheduled-posts")
async def list_queue(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(None, alias="status"),
):
    query = select(ScheduledPost).where(ScheduledPost.user_id == user.id)
    if status_filter:
        query = query.where(ScheduledPost.status == status_filter)
    rows = (
        await db.execute(query.order_by(ScheduledPost.scheduled_at.asc()).limit(300))
    ).scalars().all()

    media_map = await load_media_map(db, [r.content_candidate_id for r in rows])
    return [
        {
            "id": r.id,
            "media": media_map.get(r.content_candidate_id, []),
            "scheduled_at": r.scheduled_at,
            "status": r.status,
            "attempts": r.attempts,
            "last_error": r.last_error,
            "published_post_id": r.published_post_id,
            "x_account_id": r.x_account_id,
            "account_username": r.account.username if r.account else None,
            "text": r.candidate.generated_text if r.candidate else "",
        }
        for r in rows
    ]


@router.post("/scheduled-posts", status_code=201)
async def schedule(
    body: ScheduleIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    c = await db.get(ContentCandidate, body.content_candidate_id)
    if not c or c.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conteudo nao encontrado")
    if c.status not in ("approved", "scheduled"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Só conteudo aprovado pode ser agendado (revisao humana)."
        )
    if not c.target_x_account_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Conteudo sem conta destino")

    when = body.scheduled_at or datetime.now(timezone.utc)
    row = ScheduledPost(
        user_id=user.id,
        x_account_id=c.target_x_account_id,
        content_candidate_id=c.id,
        scheduled_at=when,
    )
    c.status = "scheduled"
    db.add(row)
    await db.commit()
    await db.refresh(row)

    if when <= datetime.now(timezone.utc) + timedelta(seconds=5):
        await enqueue("publish_scheduled", row.id)
    return {"id": row.id, "scheduled_at": row.scheduled_at, "status": row.status}


@router.post("/scheduled-posts/auto", status_code=201)
async def auto_schedule(
    body: AutoScheduleIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Espalha os aprovados usando o intervalo que o usuario escolheu.

    Cada post cai em `anterior + random(min, max)`. O sorteio serve so para o feed
    nao ficar mecanico — nao é para esconder automacao do X.
    """
    account = await db.get(XAccount, body.x_account_id)
    if not account or account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta nao encontrada")

    lo, hi = sorted((body.min_interval_minutes, body.max_interval_minutes))

    query = (
        select(ContentCandidate)
        .where(
            ContentCandidate.user_id == user.id,
            ContentCandidate.target_x_account_id == account.id,
            ContentCandidate.status == "approved",
        )
        .order_by(ContentCandidate.created_at.asc())
    )
    if body.candidate_ids:
        query = query.where(ContentCandidate.id.in_(body.candidate_ids))
    pending = (await db.execute(query)).scalars().all()
    if not pending:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Nenhum conteudo aprovado para agendar nesta conta."
        )

    # Nunca sobrepoe o que ja esta na fila desta conta.
    last = (
        await db.execute(
            select(func.max(ScheduledPost.scheduled_at)).where(
                ScheduledPost.x_account_id == account.id,
                ScheduledPost.status.in_(("queued", "publishing")),
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    cursor = now + timedelta(minutes=body.start_in_minutes)
    if last:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        cursor = max(cursor, last + timedelta(minutes=lo))

    deadline = now + timedelta(days=body.horizon_days)

    created: list[datetime] = []
    remaining = list(pending)

    if body.strategy == "optimized":
        # Horarios guiados pelo engajamento historico (Fase 5). A janela e o
        # intervalo minimo da conta continuam valendo; sem dados suficientes a
        # geracao cai no espalhamento uniforme.
        slots = await _optimized_horizon_slots(db, account, cursor, deadline)
        for slot in slots:
            if not remaining:
                break
            candidate = remaining.pop(0)
            db.add(
                ScheduledPost(
                    user_id=user.id,
                    x_account_id=account.id,
                    content_candidate_id=candidate.id,
                    scheduled_at=slot,
                )
            )
            candidate.status = "scheduled"
            created.append(slot)
    else:
        while remaining and cursor <= deadline:
            slot = (
                fit_window(cursor, account.window_start, account.window_end)
                if body.respect_window
                else cursor
            )
            if slot > deadline:
                break
            candidate = remaining.pop(0)
            db.add(
                ScheduledPost(
                    user_id=user.id,
                    x_account_id=account.id,
                    content_candidate_id=candidate.id,
                    scheduled_at=slot,
                )
            )
            candidate.status = "scheduled"
            created.append(slot)
            cursor = slot + timedelta(minutes=random.randint(lo, hi))

    db.add(
        AuditLog(
            user_id=user.id,
            action="schedule.auto",
            entity="x_account",
            entity_id=str(account.id),
            detail={
                "scheduled": len(created),
                "not_scheduled": len(remaining),
                "interval": [lo, hi],
                "horizon_days": body.horizon_days,
                "strategy": body.strategy,
            },
        )
    )
    await db.commit()
    return {
        "scheduled": len(created),
        "not_scheduled": len(remaining),
        "first": created[0] if created else None,
        "last": created[-1] if created else None,
    }


async def _optimized_horizon_slots(
    db: AsyncSession, account: XAccount, cursor: datetime, deadline: datetime
) -> list[datetime]:
    """Slots do horizonte guiados pelo engajamento historico, no fuso da conta.

    Um conjunto por dia (ate posts_per_day), escolhido pelas melhores horas de
    `PostStats`. Sem dados suficientes, cada dia cai no espalhamento uniforme —
    o agendamento nunca falha por falta de historico.
    """
    try:
        tz = ZoneInfo(account.timezone or "UTC")
    except Exception:  # noqa: BLE001
        tz = timezone.utc

    since = datetime.now(timezone.utc) - timedelta(days=90)
    rows = (
        await db.execute(
            select(PostStats, ScheduledPost)
            .join(ScheduledPost, ScheduledPost.id == PostStats.scheduled_post_id)
            .where(PostStats.x_account_id == account.id, ScheduledPost.scheduled_at >= since)
        )
    ).all()
    norm = []
    for stat, post in rows:
        published_at = post.scheduled_at
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        norm.append(
            {
                "published_at": published_at,
                "likes": stat.likes,
                "reposts": stat.reposts,
                "replies": stat.replies,
                "views": stat.views,
            }
        )
    agg = an.hourly_aggregates(norm, tz)

    per_day = min(account.posts_per_day, settings.MAX_POSTS_PER_DAY)
    min_gap = max(account.min_interval_minutes, settings.MIN_INTERVAL_MINUTES)

    slots: list[datetime] = []
    day = cursor.astimezone(tz).date()
    end_day = deadline.astimezone(tz).date()
    while day <= end_day:
        day_dt = datetime.combine(day, time.min, tzinfo=tz)
        day_slots = an.optimized_slots(
            day_dt, per_day, account.window_start, account.window_end, min_gap, agg
        )
        if day_slots is None:
            day_slots = distribute_slots(
                day_dt, per_day, account.window_start, account.window_end, min_gap
            )
        slots.extend(day_slots)
        day += timedelta(days=1)
    return [s for s in slots if cursor < s <= deadline]


@router.patch("/scheduled-posts/{post_id}")
async def reschedule(
    post_id: int,
    body: RescheduleIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(ScheduledPost, post_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item nao encontrado")
    if row.status == "published":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Post ja publicado")

    if body.scheduled_at:
        row.scheduled_at = body.scheduled_at
    if body.x_account_id:
        acc = await db.get(XAccount, body.x_account_id)
        if not acc or acc.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta nao encontrada")
        row.x_account_id = body.x_account_id
    row.status = "queued"
    await db.commit()
    return {"id": row.id, "scheduled_at": row.scheduled_at, "status": row.status}


@router.post("/scheduled-posts/{post_id}/publish-now")
async def publish_now(
    post_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    row = await db.get(ScheduledPost, post_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item nao encontrado")
    row.scheduled_at = datetime.now(timezone.utc)
    row.status = "queued"
    await db.commit()
    await enqueue("publish_scheduled", row.id)
    return {"queued": True}


@router.delete("/scheduled-posts/{post_id}")
async def cancel(
    post_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    row = await db.get(ScheduledPost, post_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item nao encontrado")
    row.status = "cancelled"
    if row.candidate and row.candidate.status == "scheduled":
        row.candidate.status = "approved"
    await db.commit()
    return {"ok": True}


# ---------- Retweet escalonado entre contas proprias ----------


@router.get("/retweets")
async def list_retweets(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(RetweetJob)
            .where(RetweetJob.user_id == user.id)
            .order_by(RetweetJob.scheduled_at.asc())
            .limit(200)
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "source_tweet_id": r.source_tweet_id,
            "target_account_id": r.target_x_account_id,
            "target_username": r.target.username if r.target else None,
            "scheduled_at": r.scheduled_at,
            "status": r.status,
            "last_error": r.last_error,
        }
        for r in rows
    ]


@router.post("/retweets", status_code=201)
async def create_retweets(
    body: RetweetIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Cria um job por conta-alvo, escalonado dentro do intervalo escolhido pelo usuario."""
    lo, hi = sorted((body.delay_min_minutes, body.delay_max_minutes))

    accounts = (
        await db.execute(
            select(XAccount).where(
                XAccount.user_id == user.id,
                XAccount.id.in_(body.target_account_ids),
                XAccount.is_active.is_(True),
            )
        )
    ).scalars().all()
    if not accounts:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nenhuma conta destino valida")

    now = datetime.now(timezone.utc)
    cursor = now
    created = []
    for acc in accounts:
        if acc.id == body.origin_x_account_id:
            continue  # a conta autora nao retweeta a si mesma
        cursor += timedelta(minutes=random.randint(lo, hi))
        job = RetweetJob(
            user_id=user.id,
            source_tweet_id=body.source_tweet_id,
            origin_x_account_id=body.origin_x_account_id,
            target_x_account_id=acc.id,
            scheduled_at=cursor,
        )
        db.add(job)
        created.append(job)

    db.add(
        AuditLog(
            user_id=user.id,
            action="retweet.scheduled",
            entity="tweet",
            entity_id=body.source_tweet_id,
            detail={"targets": [a.username for a in accounts], "delay_range": [lo, hi]},
        )
    )
    await db.commit()
    return {"created": len(created)}


@router.delete("/retweets/{job_id}")
async def cancel_retweet(
    job_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    row = await db.get(RetweetJob, job_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job nao encontrado")
    row.status = "cancelled"
    await db.commit()
    return {"ok": True}
