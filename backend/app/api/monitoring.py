"""Fontes monitoradas, pool manual de textos e posts coletados."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import current_user
from app.db import get_db
from app.models import ManualSourceText, MonitoredAccount, SourcePost, User
from app.workers import enqueue

router = APIRouter(prefix="/api", tags=["monitoring"])


class MonitoredIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = ""
    x_user_id: str = ""
    source_type: str = "manual"


class ManualTextIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    tags: list[str] = []


# ---------- Contas monitoradas ----------


@router.get("/monitoring/accounts")
async def list_monitored(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(MonitoredAccount)
            .where(MonitoredAccount.user_id == user.id)
            .order_by(MonitoredAccount.id)
        )
    ).scalars().all()

    counts = dict(
        (
            await db.execute(
                select(SourcePost.monitored_account_id, func.count(SourcePost.id))
                .where(SourcePost.user_id == user.id)
                .group_by(SourcePost.monitored_account_id)
            )
        ).all()
    )
    return [
        {
            "id": r.id,
            "username": r.username,
            "display_name": r.display_name,
            "source_type": r.source_type,
            "is_active": r.is_active,
            "last_collected_at": r.last_collected_at,
            "posts_found": counts.get(r.id, 0),
            "engagement_baseline": r.engagement_baseline or {},
        }
        for r in rows
    ]


@router.post("/monitoring/accounts", status_code=201)
async def add_monitored(
    body: MonitoredIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    row = MonitoredAccount(
        user_id=user.id,
        username=body.username.lstrip("@"),
        display_name=body.display_name,
        x_user_id=body.x_user_id,
        source_type=body.source_type if body.source_type in ("manual", "x_api") else "manual",
    )
    db.add(row)
    await db.commit()
    return {"id": row.id, "username": row.username}


class MonitoredUpdate(BaseModel):
    source_type: str | None = None
    is_active: bool | None = None


@router.patch("/monitoring/accounts/{account_id}")
async def update_monitored(
    account_id: int,
    body: MonitoredUpdate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(MonitoredAccount, account_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fonte nao encontrada")
    if body.source_type in ("manual", "x_api"):
        row.source_type = body.source_type
    if body.is_active is not None:
        row.is_active = body.is_active
    await db.commit()
    return {"id": row.id, "source_type": row.source_type, "is_active": row.is_active}


@router.delete("/monitoring/accounts/{account_id}")
async def remove_monitored(
    account_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    row = await db.get(MonitoredAccount, account_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fonte nao encontrada")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.post("/monitoring/accounts/{account_id}/collect")
async def collect_now(
    account_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    row = await db.get(MonitoredAccount, account_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fonte nao encontrada")
    await enqueue("collect_account", account_id)
    return {"queued": True}


# ---------- Pool manual de textos (fonte custo-zero) ----------


@router.get("/manual-texts")
async def list_texts(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(ManualSourceText)
            .where(ManualSourceText.user_id == user.id)
            .order_by(ManualSourceText.id.desc())
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "text": r.text,
            "tags": r.tags or [],
            "is_active": r.is_active,
            "used_count": r.used_count,
        }
        for r in rows
    ]


@router.post("/manual-texts", status_code=201)
async def add_texts(
    body: list[ManualTextIn], user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Aceita lote — o painel permite colar varios textos de uma vez."""
    rows = [ManualSourceText(user_id=user.id, text=b.text.strip(), tags=b.tags) for b in body]
    db.add_all(rows)
    await db.commit()
    return {"created": len(rows)}


@router.get("/manual-texts/{text_id}")
async def get_text(
    text_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    row = await db.get(ManualSourceText, text_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Texto nao encontrado")
    return {"id": row.id, "text": row.text, "tags": row.tags or [], "used_count": row.used_count}


@router.delete("/manual-texts/{text_id}")
async def delete_text(
    text_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    row = await db.get(ManualSourceText, text_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Texto nao encontrado")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ---------- Posts coletados ----------


@router.get("/source-posts")
async def list_source_posts(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    order: str = Query("score", pattern="^(score|recent)$"),
    limit: int = Query(50, le=200),
):
    query = select(SourcePost).where(SourcePost.user_id == user.id)
    query = query.order_by(
        SourcePost.score.desc() if order == "score" else SourcePost.collected_at.desc()
    ).limit(limit)
    rows = (await db.execute(query)).scalars().all()
    return [
        {
            "id": r.id,
            "text": r.text,
            "author_username": r.author_username,
            "posted_at": r.posted_at,
            "likes": r.likes,
            "reposts": r.reposts,
            "replies": r.replies,
            "views": r.views,
            "has_media": r.has_media,
            "original_url": r.original_url,
            "score": r.score,
            "score_breakdown": r.score_breakdown or {},
        }
        for r in rows
    ]
