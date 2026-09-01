"""Piloto automatico (opt-in por conta, XAccount.auto_pilot).

Duas partes:
  - `next_auto_slot`: proximo horario livre pra uma conta (cadencia de
    1-2h — ou o minimo da conta, se maior —, teto diario, janela). Usado no
    aprovar (content.py) pra agendar sem o usuario escolher data/hora.
  - `sweep`: varredura periodica (chamada pelo worker) que gera rascunhos
    novos pras contas que estao com a fila de hoje abaixo do teto —
    distribuicao pareada entre contas por construcao (cada conta so' recebe
    deficit da SUA propria fila, nunca do total). Cada post de origem e'
    usado no maximo uma vez (nunca vira conteudo duas vezes, em conta
    nenhuma). Sai sempre `pending` — aprovacao humana continua obrigatoria.
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AIGeneration,
    AuditLog,
    CandidateMedia,
    ContentCandidate,
    MediaAsset,
    ScheduledPost,
    SourcePost,
    XAccount,
)
from app.services import ai, dedup, reword
from app.services.scheduling import fit_window

log = logging.getLogger("autopilot")

# Ancora da cadencia (1-2h desde o ultimo post, esteja ele so' na fila ou ja
# publicado — senao um post recem-publicado fica "invisivel" pro calculo e o
# proximo cai cedo demais, so' sendo salvo pelo piso de _enforce_pacing).
_CADENCE_ANCHOR_STATUSES = ("queued", "publishing", "published")
_COUNTS_TOWARD_DAY = ("queued", "publishing", "published")


def _local_date(dt: datetime, tz: ZoneInfo) -> "datetime.date":
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).date()


async def _count_scheduled_on(db: AsyncSession, account: XAccount, moment: datetime) -> int:
    tz = _tz(account)
    day = _local_date(moment, tz)
    day_start_local = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    day_end_local = day_start_local + timedelta(days=1)
    rows = (
        await db.execute(
            select(ScheduledPost.scheduled_at).where(
                ScheduledPost.x_account_id == account.id,
                ScheduledPost.status.in_(_COUNTS_TOWARD_DAY),
                ScheduledPost.scheduled_at >= day_start_local.astimezone(timezone.utc),
                ScheduledPost.scheduled_at < day_end_local.astimezone(timezone.utc),
            )
        )
    ).scalars().all()
    return len(rows)


def _tz(account: XAccount) -> ZoneInfo:
    try:
        return ZoneInfo(account.timezone or "UTC")
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


async def next_auto_slot(db: AsyncSession, account: XAccount) -> datetime:
    """Proximo horario livre pra conta: cadencia 1-2h (piso da conta se maior),
    teto diario (posts_per_day), dentro da janela. Nunca falha — no pior caso
    empurra pro dia seguinte ate achar espaco (limite de 30 dias de seguranca)."""
    lo = max(account.min_interval_minutes, settings.AUTOPILOT_MIN_GAP_MINUTES)
    hi = max(lo, settings.AUTOPILOT_MAX_GAP_MINUTES)
    target_per_day = min(account.posts_per_day, settings.MAX_POSTS_PER_DAY)

    now = datetime.now(timezone.utc)
    last = (
        await db.execute(
            select(func.max(ScheduledPost.scheduled_at)).where(
                ScheduledPost.x_account_id == account.id,
                ScheduledPost.status.in_(_CADENCE_ANCHOR_STATUSES),
            )
        )
    ).scalar_one_or_none()

    cursor = now + timedelta(minutes=5)
    if last:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        cursor = max(cursor, last + timedelta(minutes=random.randint(lo, hi)))

    # window_start/window_end sao horario LOCAL da conta — fit_window precisa
    # operar no fuso da conta, senao "08:00-23:00" vira 08:00-23:00 UTC.
    tz = _tz(account)
    for _ in range(30):
        local_cursor = cursor.astimezone(tz)
        local_slot = fit_window(local_cursor, account.window_start, account.window_end)
        slot = local_slot.astimezone(timezone.utc)
        if await _count_scheduled_on(db, account, slot) < target_per_day:
            return slot
        # Teto do dia batido: tenta a abertura da janela do dia seguinte.
        sh, sm = (int(x) for x in account.window_start.split(":"))
        cursor = (local_slot + timedelta(days=1)).replace(hour=sh, minute=sm).astimezone(timezone.utc)
    return cursor  # limite de seguranca (nao deveria chegar aqui na pratica)


async def _generate_text(account: XAccount, source_text: str) -> tuple[str, dict | None]:
    """(texto, usage_ou_None). usage None = nao usou IA (fast ou fallback)."""
    if account.content_mode == "fast" or not ai.provider.available():
        return reword.reword(source_text), None
    try:
        angles, usage = await asyncio.wait_for(
            ai.provider.generate_angles(source_text, account.persona_prompt, 1),
            timeout=settings.AUTOPILOT_AI_TIMEOUT_SECONDS,
        )
        if angles:
            return angles[0][:280], usage
    except Exception as exc:  # noqa: BLE001
        log.warning("Piloto automatico: IA falhou/demorou pra @%s (%s) — caiu pra rapida", account.username, exc)
    return reword.reword(source_text), None


async def sweep(db: AsyncSession) -> dict:
    accounts = (
        await db.execute(
            select(XAccount).where(XAccount.auto_pilot.is_(True), XAccount.is_active.is_(True))
        )
    ).scalars().all()

    created_total = 0
    per_account: dict[str, int] = {}

    for account in accounts:
        target_per_day = min(account.posts_per_day, settings.MAX_POSTS_PER_DAY)
        now = datetime.now(timezone.utc)
        scheduled_today = await _count_scheduled_on(db, account, now)
        pending_backlog = (
            await db.execute(
                select(func.count()).select_from(ContentCandidate).where(
                    ContentCandidate.target_x_account_id == account.id,
                    ContentCandidate.status == "pending",
                )
            )
        ).scalar_one()

        deficit = target_per_day - scheduled_today - pending_backlog
        if deficit <= 0:
            continue
        take = min(deficit, settings.AUTOPILOT_PER_ACCOUNT_CAP)

        # Nunca reusa post de origem que ja virou conteudo (em qualquer conta).
        used = select(ContentCandidate.source_post_id).where(
            ContentCandidate.source_post_id.is_not(None)
        )
        posts = (
            await db.execute(
                select(SourcePost)
                .where(
                    SourcePost.user_id == account.user_id,
                    ~exists(used.where(ContentCandidate.source_post_id == SourcePost.id)),
                )
                .order_by(SourcePost.score.desc())
                .limit(take)
            )
        ).scalars().all()
        if not posts:
            log.info("Piloto automatico: sem post novo pra @%s (colete mais)", account.username)
            continue

        media_pool: list[MediaAsset] = []
        if settings.MEDIA_REQUIRED:
            media_pool = (
                await db.execute(
                    select(MediaAsset).where(
                        MediaAsset.user_id == account.user_id,
                        MediaAsset.origin.in_(MediaAsset.PUBLISHABLE),
                    )
                )
            ).scalars().all()
            if not media_pool:
                log.info(
                    "Piloto automatico: sem midia propria/licenciada pra @%s — nada gerado",
                    account.username,
                )
                continue

        made_for_account = 0
        for post in posts:
            text, usage = await _generate_text(account, post.text)
            if not text.strip():
                continue

            candidate = ContentCandidate(
                user_id=account.user_id,
                source_post_id=post.id,
                target_x_account_id=account.id,
                generated_text=text,
                origin="ai" if usage else "manual",
                status="pending",
                content_hash=dedup.content_hash(text),
            )
            db.add(candidate)
            await db.flush()

            if media_pool:
                db.add(
                    CandidateMedia(
                        content_candidate_id=candidate.id,
                        media_asset_id=random.choice(media_pool).id,
                        position=0,
                    )
                )
            if usage:
                db.add(
                    AIGeneration(
                        user_id=account.user_id,
                        source_post_id=post.id,
                        target_account_id=account.id,
                        prompt=usage["prompt"],
                        response=usage["raw"],
                        model=usage["model"],
                        tokens_input=usage["tokens_input"],
                        tokens_output=usage["tokens_output"],
                    )
                )
            created_total += 1
            made_for_account += 1
            per_account[account.username] = per_account.get(account.username, 0) + 1

        if made_for_account:
            db.add(
                AuditLog(
                    user_id=account.user_id,
                    action="autopilot.generated",
                    entity="x_account",
                    entity_id=str(account.id),
                    detail={"count": made_for_account, "account": account.username},
                )
            )

    if created_total:
        await db.commit()
        log.info("Piloto automatico: %d rascunho(s) novo(s) — %s", created_total, per_account)
    return {"created": created_total, "per_account": per_account}
