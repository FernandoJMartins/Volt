"""Analytics dos posts publicados e otimizacao de horarios (Fase 5).

Dados vêm de `PostStats` — engajamento coletado pelo worker via navegador
(perfil proprio, sem custo de API). Este router so agrega e expoe; a logica
pura (horas melhores, slots otimizados) fica em `app.services.analytics`.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import current_user
from app.db import get_db
from app.models import Account, MonitoredAccount, PostStats, ScheduledPost, SourcePost, User
from app.services import analytics as an
from app.services import platform_web
from app.services.scheduling import distribute_slots
from app.workers import enqueue

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

LOOKBACK_DAYS = 90


def _account_tz(account: Account):
    try:
        return ZoneInfo(account.timezone or "UTC")
    except Exception:  # noqa: BLE001
        return timezone.utc


def _stat_rows(rows: list[tuple[PostStats, ScheduledPost]]) -> list[dict]:
    """Normaliza (PostStats, ScheduledPost) para o formato do service."""
    out = []
    for stat, post in rows:
        published_at = post.scheduled_at
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        out.append(
            {
                "published_at": published_at,
                "likes": stat.likes,
                "reposts": stat.reposts,
                "replies": stat.replies,
                "views": stat.views,
            }
        )
    return out


@router.get("/overview")
async def overview(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    account_id: int | None = Query(None),
):
    """Agregado por conta: volume, engajamento medio, mapa por hora do dia,
    melhores horarios e posts recentes com metricas."""
    accounts_q = select(Account).where(Account.user_id == user.id)
    if account_id is not None:
        accounts_q = accounts_q.where(Account.id == account_id)
    accounts = (await db.execute(accounts_q)).scalars().all()

    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    rows = (
        await db.execute(
            select(PostStats, ScheduledPost)
            .join(ScheduledPost, ScheduledPost.id == PostStats.scheduled_post_id)
            .where(PostStats.user_id == user.id, ScheduledPost.scheduled_at >= since)
            .order_by(ScheduledPost.scheduled_at.desc())
        )
    ).all()

    # Volume publicado por conta (todos, inclusive posts ainda sem stats).
    published_by_account = dict(
        (
            await db.execute(
                select(ScheduledPost.account_id, func.count())
                .where(ScheduledPost.user_id == user.id, ScheduledPost.status == "published")
                .group_by(ScheduledPost.account_id)
            )
        ).all()
    )

    by_account: dict[int, list] = {}
    for stat, post in rows:
        by_account.setdefault(stat.account_id, []).append((stat, post))

    out = []
    for acc in accounts:
        tz = _account_tz(acc)
        pairs = by_account.get(acc.id, [])
        norm = _stat_rows(pairs)
        agg = an.hourly_aggregates(norm, tz)
        prior = an._global_prior(agg)

        best = an.best_hours(
            agg,
            acc.window_start,
            acc.window_end,
            count=min(3, max(1, acc.posts_per_day)),
            min_gap_minutes=max(acc.min_interval_minutes, 15),
        )

        recent = []
        for stat, post in pairs[:10]:
            recent.append(
                {
                    "id": post.id,
                    "url": platform_web.driver_for(acc.platform).post_url(acc.username, post.published_post_id),
                    "text": (post.candidate.generated_text if post.candidate else "")[:140],
                    "published_at": post.scheduled_at,
                    "likes": stat.likes,
                    "reposts": stat.reposts,
                    "replies": stat.replies,
                    "views": stat.views,
                }
            )

        posts_with_stats = len(pairs)
        total_weighted = sum(b["weighted"] for b in agg.values())
        out.append(
            {
                "account_id": acc.id,
                "platform": acc.platform,
                "username": acc.username,
                "display_name": acc.display_name,
                "avatar_url": acc.avatar_url,
                "published": int(published_by_account.get(acc.id, 0)),
                "with_stats": posts_with_stats,
                "avg_likes": round(sum(s["likes"] for s in norm) / posts_with_stats, 1) if posts_with_stats else 0,
                "avg_reposts": round(sum(s["reposts"] for s in norm) / posts_with_stats, 1) if posts_with_stats else 0,
                "avg_replies": round(sum(s["replies"] for s in norm) / posts_with_stats, 1) if posts_with_stats else 0,
                "avg_views": round(sum(s["views"] for s in norm) / posts_with_stats, 1) if posts_with_stats else 0,
                "engagement_per_post": round(total_weighted / posts_with_stats, 2) if posts_with_stats else 0,
                "hourly": [
                    {"hour": h, "score": round(an.hour_score(agg[h], prior), 2), **agg[h]}
                    for h in range(24)
                ],
                "best_hours": best or [],
                "recent": recent,
                "last_collected_at": (
                    pairs[0][0].last_collected_at if pairs else None
                ),
            }
        )
    return out


@router.get("/sources")
async def sources_overview(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Analytics das CONTAS CLONADAS (fontes monitoradas): volume coletado,
    engajamento medio, mapa por hora e melhores horas de cada perfil.

    Diferenca para /overview: la' sao as SUAS contas (posts que VOCE publicou);
    aqui sao os perfis de inspiracao (posts coletados deles).
    """
    monitored = (
        await db.execute(
            select(MonitoredAccount).where(MonitoredAccount.user_id == user.id)
        )
    ).scalars().all()

    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    posts = (
        await db.execute(
            select(SourcePost)
            .where(
                SourcePost.user_id == user.id,
                SourcePost.collected_at >= since,
            )
            .order_by(SourcePost.collected_at.desc())
        )
    ).scalars().all()

    by_source: dict[int, list] = {}
    for p in posts:
        if p.monitored_account_id is not None:
            by_source.setdefault(p.monitored_account_id, []).append(p)

    out = []
    for m in monitored:
        rows = by_source.get(m.id, [])
        norm = []
        for p in rows:
            posted = p.posted_at
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
            norm.append(
                {
                    "published_at": posted,
                    "likes": p.likes,
                    "reposts": p.reposts,
                    "replies": p.replies,
                    "views": p.views,
                }
            )
        agg = an.hourly_aggregates(norm, timezone.utc)
        prior = an._global_prior(agg)
        best = an.best_hours(agg, "00:00", "23:00", count=3, min_gap_minutes=30)

        n = len(rows)
        out.append(
            {
                "id": m.id,
                "username": m.username,
                "display_name": m.display_name,
                "collected": n,
                "avg_likes": round(sum(p.likes for p in rows) / n, 1) if n else 0,
                "avg_reposts": round(sum(p.reposts for p in rows) / n, 1) if n else 0,
                "avg_replies": round(sum(p.replies for p in rows) / n, 1) if n else 0,
                "avg_views": round(sum(p.views for p in rows) / n, 1) if n else 0,
                "hourly": [
                    {"hour": h, "score": round(an.hour_score(agg[h], prior), 2), **agg[h]}
                    for h in range(24)
                ],
                "best_hours": best or [],
                "last_collected_at": m.last_collected_at,
            }
        )
    return out


@router.get("/best-times")
async def best_times(
    account_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    count: int = Query(3, ge=1, le=12),
    day: date | None = Query(None),
):
    """Sugere horarios para publicar `count` posts no dia `day` (padrao: amanha,
    no fuso da conta), ponderados pelo engajamento historico por hora.

    Sem dados suficientes, cai no espalhamento uniforme (source=fallback) —
    a otimizacao nunca bloqueia o agendamento.
    """
    account = await db.get(Account, account_id)
    if not account or account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta nao encontrada")

    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    rows = (
        await db.execute(
            select(PostStats, ScheduledPost)
            .join(ScheduledPost, ScheduledPost.id == PostStats.scheduled_post_id)
            .where(PostStats.account_id == account.id, ScheduledPost.scheduled_at >= since)
        )
    ).all()

    tz = _account_tz(account)
    norm = _stat_rows(rows)
    agg = an.hourly_aggregates(norm, tz)

    if day is None:
        day = (datetime.now(tz) + timedelta(days=1)).date()
    day_dt = datetime.combine(day, time.min, tzinfo=tz)

    min_gap = max(account.min_interval_minutes, 15)
    slots = an.optimized_slots(
        day_dt, count, account.window_start, account.window_end, min_gap, agg
    )
    source = "data"
    if slots is None:
        slots = distribute_slots(
            day_dt, count, account.window_start, account.window_end, min_gap
        )
        source = "fallback"

    best = an.best_hours(
        agg, account.window_start, account.window_end, count=count, min_gap_minutes=min_gap
    )
    return {
        "account_id": account.id,
        "date": day.isoformat(),
        "timezone": str(tz),
        "source": source,
        "best_hours": best or [],
        "slots": [s.isoformat() for s in slots],
    }


@router.post("/refresh")
async def refresh(
    account_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dispara agora a coleta de engajamento da conta (1 navegacao no navegador)."""
    account = await db.get(Account, account_id)
    if not account or account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta nao encontrada")
    if not account.session_state_encrypted:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Conta sem sessao de navegador conectada."
        )
    await enqueue("collect_post_stats", account.id)
    return {"queued": True, "account_id": account.id}
