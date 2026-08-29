from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import current_user
from app.db import get_db
from app.models import ContentCandidate, ScheduledPost, SourcePost, User, XAccount

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
async def stats(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    today = datetime.now(timezone.utc) - timedelta(hours=24)

    async def count(model, *conditions) -> int:
        query = select(func.count(model.id)).where(model.user_id == user.id, *conditions)
        return (await db.execute(query)).scalar_one()

    return {
        "connected_accounts": await count(XAccount, XAccount.is_active.is_(True)),
        "posts_today": await count(SourcePost, SourcePost.collected_at >= today),
        "posts_total": await count(SourcePost),
        "pending_review": await count(ContentCandidate, ContentCandidate.status == "pending"),
        "approved": await count(ContentCandidate, ContentCandidate.status == "approved"),
        "blocked": await count(ContentCandidate, ContentCandidate.status == "blocked"),
        "queued": await count(ScheduledPost, ScheduledPost.status == "queued"),
        "published": await count(ScheduledPost, ScheduledPost.status == "published"),
        "failed": await count(ScheduledPost, ScheduledPost.status == "failed"),
    }
