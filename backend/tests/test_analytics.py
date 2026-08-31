"""Testes da logica de analytics/otimizacao de horarios (Fase 5).

Sem banco, sem navegador — so a logica pura de app/services/analytics.py.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services import analytics as an

SAO = ZoneInfo("America/Sao_Paulo")


def row(day_offset: int, hour: int, likes: int, reposts: int = 0, replies: int = 0) -> dict:
    """Linha de post publicada as `hour`h (fuso local) num dado dia."""
    base = datetime(2026, 8, 3, tzinfo=SAO)  # segunda-feira
    published = (base - timedelta(days=day_offset)).replace(
        hour=hour, minute=30, second=0, microsecond=0
    )
    return {
        "published_at": published,
        "likes": likes,
        "reposts": reposts,
        "replies": replies,
        "views": 0,
    }


def test_weighted_engagement_weights_reposts_higher():
    assert an.weighted_engagement(1, 0, 0) == 1.0
    assert an.weighted_engagement(0, 1, 0) == 2.0
    assert an.weighted_engagement(0, 0, 1) == 1.5


def test_hourly_aggregates_groups_by_account_timezone():
    # 12h UTC == 09h em Sao Paulo (UTC-3 em agosto).
    utc = timezone.utc
    rows = [
        {"published_at": datetime(2026, 8, 3, 12, 0, tzinfo=utc), "likes": 10, "reposts": 2, "replies": 4, "views": 100},
        {"published_at": datetime(2026, 8, 4, 13, 0, tzinfo=utc), "likes": 5, "reposts": 0, "replies": 0, "views": 50},
    ]
    agg = an.hourly_aggregates(rows, SAO)

    assert agg[9]["posts"] == 1
    assert agg[9]["likes"] == 10
    assert agg[10]["posts"] == 1  # 13h UTC == 10h em SP
    assert agg[9]["weighted"] == 10 + 4 + 6  # likes + 2*reposts + 1.5*replies
    assert agg[0]["posts"] == 0
    assert all(h in agg for h in range(24))


def test_hourly_aggregates_rejects_naive_datetime():
    import pytest

    with pytest.raises(ValueError):
        an.hourly_aggregates(
            [{"published_at": datetime(2026, 8, 3, 9, 0), "likes": 1, "reposts": 0, "replies": 0, "views": 0}],
            SAO,
        )


def test_best_hours_prefers_hour_with_higher_engagement():
    rows = []
    for _ in range(10):
        rows.append(row(0, 8, likes=1))
        rows.append(row(0, 20, likes=8))
    agg = an.hourly_aggregates(rows, SAO)

    # count=1: a unica escolha e' a hora de maior engajamento.
    best = an.best_hours(agg, "08:00", "23:00", count=1, min_gap_minutes=30)
    assert best == [20]

    # count=3 com so 2 horas elegiveis: ambas entram (ordem crescente de hora).
    best_all = an.best_hours(agg, "08:00", "23:00", count=3, min_gap_minutes=30)
    assert best_all == [8, 20]


def test_best_hours_respects_min_gap():
    rows = [row(0, 8, likes=5), row(0, 9, likes=4), row(0, 12, likes=3)]
    agg = an.hourly_aggregates(rows, SAO)

    # Com gap de 3h, 9h nao pode ficar ao lado de 8h.
    best = an.best_hours(agg, "08:00", "23:00", count=2, min_gap_minutes=180)
    assert best == [8, 12]


def test_best_hours_returns_none_without_data():
    agg = an.hourly_aggregates([], SAO)
    assert an.best_hours(agg, "08:00", "23:00", count=3, min_gap_minutes=30) is None


def test_hour_score_smooths_small_samples():
    # Um unico post anomalo (100 de engajamento) nao pode ter score 10x maior
    # que uma hora com 20 posts solidos de 5 cada.
    rows = [row(0, 9, likes=100)]
    for _ in range(20):
        rows.append(row(0, 18, likes=5))
    agg = an.hourly_aggregates(rows, SAO)
    prior = an._global_prior(agg)

    one_hit = an.hour_score(agg[9], prior)
    solid = an.hour_score(agg[18], prior)
    assert one_hit > prior  # acima da media, mas...
    assert one_hit < 10 * solid  # ...nao em ordem de grandeza diferente
    assert an.hour_score(agg[4], prior) == prior  # sem post == prior


def test_optimized_slots_within_window_count_and_gap():
    rows = [row(0, 10, likes=9), row(0, 11, likes=9), row(0, 16, likes=2)]
    agg = an.hourly_aggregates(rows, SAO)

    day = datetime(2026, 8, 4, tzinfo=SAO)
    slots = an.optimized_slots(day, count=2, window_start="08:00", window_end="17:00",
                               min_gap_minutes=30, agg=agg)
    assert slots is not None
    assert len(slots) == 2
    assert all(8 <= s.hour <= 17 for s in slots)
    # A melhor hora (10h) aparece no primeiro slot.
    assert slots[0].hour == 10
    for a, b in zip(slots, slots[1:]):
        assert (b - a) >= timedelta(minutes=30)


def test_optimized_slots_deterministic():
    agg = an.hourly_aggregates([row(0, 10, likes=5)], SAO)
    day = datetime(2026, 8, 4, tzinfo=SAO)
    first = an.optimized_slots(day, 2, "08:00", "17:00", 30, agg)
    second = an.optimized_slots(day, 2, "08:00", "17:00", 30, agg)
    assert first == second


def test_optimized_slots_fallback_none_without_data():
    agg = an.hourly_aggregates([], SAO)
    day = datetime(2026, 8, 4, tzinfo=SAO)
    assert an.optimized_slots(day, 2, "08:00", "17:00", 30, agg) is None


def test_window_hours():
    assert an.window_hours("08:00", "23:00") == list(range(8, 24))
    assert an.window_hours("00:00", "01:00") == [0, 1]
