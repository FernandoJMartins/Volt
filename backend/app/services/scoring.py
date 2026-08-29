"""Score de potencial de engajamento.

O ponto central: `relative_strength` compara o post com a media da PROPRIA conta,
para que contas grandes nao dominem o ranking so por terem numeros absolutos maiores.
"""

import math
from datetime import datetime, timezone

from app.config import settings

# Peso relativo das interacoes: repost sinaliza mais intencao que like.
_LIKE_W, _REPOST_W, _REPLY_W = 1.0, 2.0, 1.5


def engagement_rate(likes: int, reposts: int, replies: int, views: int) -> float:
    weighted = likes * _LIKE_W + reposts * _REPOST_W + replies * _REPLY_W
    # Sem views (fonte manual ou API sem metrica), usa o proprio peso como escala.
    return weighted / max(views, 1) if views else weighted / 100.0


def compute_score(
    *,
    likes: int,
    reposts: int,
    replies: int,
    views: int,
    has_media: bool,
    posted_at: datetime,
    baseline: dict | None = None,
) -> tuple[float, dict]:
    now = datetime.now(timezone.utc)
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    age_hours = max((now - posted_at).total_seconds() / 3600, 0.05)

    rate = engagement_rate(likes, reposts, replies, views)
    base_rate = (baseline or {}).get("engagement_rate") or 0.0
    # Sem baseline ainda, trata o post como mediano (1.0) em vez de inflar o score.
    relative_strength = rate / base_rate if base_rate > 0 else 1.0

    total = likes * _LIKE_W + reposts * _REPOST_W + replies * _REPLY_W
    velocity = total / age_hours
    recency = math.exp(-age_hours / settings.SCORE_HALFLIFE_HOURS)
    media_bonus = 1.0 if has_media else 0.0

    score = (
        settings.SCORE_W_RELATIVE * relative_strength
        + settings.SCORE_W_VELOCITY * math.log1p(velocity)
        + settings.SCORE_W_RECENCY * recency
        + settings.SCORE_W_MEDIA * media_bonus
    )

    breakdown = {
        "engagement_rate": round(rate, 6),
        "relative_strength": round(relative_strength, 4),
        "velocity": round(velocity, 4),
        "recency": round(recency, 4),
        "media_bonus": media_bonus,
        "age_hours": round(age_hours, 2),
    }
    return round(score, 4), breakdown


def update_baseline(baseline: dict | None, rate: float, alpha: float = 0.2) -> dict:
    """Media movel exponencial do engajamento da conta monitorada."""
    baseline = dict(baseline or {})
    previous = baseline.get("engagement_rate")
    baseline["engagement_rate"] = rate if previous is None else (1 - alpha) * previous + alpha * rate
    baseline["samples"] = int(baseline.get("samples", 0)) + 1
    return baseline
