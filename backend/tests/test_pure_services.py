"""Testes das logicas puras: scoring, dedup e distribuicao de horarios."""

from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.services import scoring
from app.services.dedup import content_hash, find_conflict, normalize, similarity
from app.services.scheduling import distribute_slots, fit_window
from app.services.reword import reword
from app.services.ai import _parse_angles


# ---------------- scoring ----------------


def test_engagement_rate_weighted() -> None:
    rate = scoring.engagement_rate(likes=10, reposts=2, replies=0, views=1000)
    assert rate == pytest.approx((10 * 1.0 + 2 * 2.0 + 0 * 1.5) / 1000)


def test_engagement_rate_without_views_uses_scale() -> None:
    rate = scoring.engagement_rate(likes=10, reposts=0, replies=0, views=0)
    assert rate == pytest.approx(10.0 / 100.0)


def test_fresh_post_scores_higher_than_old() -> None:
    now = datetime.now(timezone.utc)
    fresh, _ = scoring.compute_score(
        likes=10, reposts=0, replies=0, views=1000, has_media=False, posted_at=now
    )
    old, _ = scoring.compute_score(
        likes=10, reposts=0, replies=0, views=1000,
        has_media=False, posted_at=now - timedelta(hours=48),
    )
    assert fresh > old


def test_baseline_dampens_relative_strength() -> None:
    now = datetime.now(timezone.utc)
    kwargs = dict(likes=10, reposts=0, replies=0, views=1000, has_media=False, posted_at=now)
    _, no_baseline = scoring.compute_score(**kwargs)
    _, with_baseline = scoring.compute_score(
        **kwargs, baseline={"engagement_rate": 1.0}  # conta forte: mesmo post e' comum
    )
    assert no_baseline["relative_strength"] == 1.0
    assert with_baseline["relative_strength"] < 1.0


def test_update_baseline_ema() -> None:
    b = scoring.update_baseline(None, rate=0.5)
    assert b["engagement_rate"] == 0.5 and b["samples"] == 1
    b = scoring.update_baseline(b, rate=0.1, alpha=0.2)
    assert b["engagement_rate"] == pytest.approx(0.8 * 0.5 + 0.2 * 0.1)
    assert b["samples"] == 2


# ---------------- dedup ----------------


def test_normalize() -> None:
    assert normalize("  Olá,   MUNDO! ") == "ola mundo"
    assert normalize("https://x.com/foo bar") == "bar"


def test_content_hash_identical_after_normalize() -> None:
    assert content_hash("Olá MUNDO!") == content_hash("ola   mundo")


def test_similarity_extremes() -> None:
    assert similarity("mudar o mundo", "mudar o mundo") == pytest.approx(1.0)
    assert similarity("mudar o mundo", "comprar pão") < 0.3


def test_find_conflict_catches_near_identical_but_not_unrelated() -> None:
    existing = [(1, "este e um exemplo de teste automatizado", "@conta_a")]
    hit = find_conflict(
        "este e um exemplo de teste automatizados", existing, settings.SIMILARITY_THRESHOLD
    )
    assert hit is not None and hit["id"] == 1 and hit["kind"] == "similar"
    miss = find_conflict("comprei pao na padaria", existing, settings.SIMILARITY_THRESHOLD)
    assert miss is None


def test_single_word_paraphrase_below_threshold_is_allowed() -> None:
    # Troca de UMA palavra em texto curto mede ~0.6-0.7: o limiar 0.75 e'
    # conservador de proposito (evita falso bloqueio). Este teste documenta
    # o comportamento atual — se o limiar mudar de proposito, ajuste aqui.
    s = similarity("vamos mudar o mundo hoje", "vamos transformar o mundo hoje")
    assert 0.6 < s < settings.SIMILARITY_THRESHOLD


def test_find_conflict_identical_kind() -> None:
    existing = [(1, "exatamente igual", "@conta_a")]
    hit = find_conflict("exatamente igual", existing, settings.SIMILARITY_THRESHOLD)
    assert hit["kind"] == "identico" and hit["similarity"] == 1.0


# ---------------- scheduling ----------------


def test_distribute_slots_basic() -> None:
    day = datetime(2026, 1, 1)
    slots = distribute_slots(day, count=5, window_start="08:00", window_end="20:00",
                             min_gap_minutes=30, seed=1)
    assert len(slots) == 5
    for s in slots:
        assert day.replace(hour=8) <= s <= day.replace(hour=20)
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(slots, slots[1:])]
    assert all(g >= 30 for g in gaps)


def test_distribute_slots_deterministic() -> None:
    kwargs = dict(day=datetime(2026, 1, 1), count=5, window_start="08:00",
                  window_end="20:00", min_gap_minutes=30, seed=42)
    assert distribute_slots(**kwargs) == distribute_slots(**kwargs)


def test_distribute_slots_caps_by_min_gap() -> None:
    # Janela de 60 min com gap minimo de 30 -> cabem no maximo 3 slots; o jitter
    # deterministico pode empurrar o ultimo alem do fim da janela. O contrato e':
    # nunca violar o gap minimo nem passar do fim.
    slots = distribute_slots(datetime(2026, 1, 1), count=10, window_start="08:00",
                             window_end="09:00", min_gap_minutes=30, seed=0)
    assert 1 <= len(slots) <= 3
    for s in slots:
        assert datetime(2026, 1, 1, 8) <= s <= datetime(2026, 1, 1, 9)
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(slots, slots[1:])]
    assert all(g >= 30 for g in gaps)


def test_distribute_slots_edge_cases() -> None:
    assert distribute_slots(datetime(2026, 1, 1), count=0, window_start="08:00",
                            window_end="20:00", min_gap_minutes=30) == []
    # Janela invertida (fim antes do inicio) -> vazio, sem erro.
    assert distribute_slots(datetime(2026, 1, 1), count=5, window_start="20:00",
                            window_end="08:00", min_gap_minutes=30) == []


def test_fit_window_before_pushes_to_opening() -> None:
    moment = datetime(2026, 1, 1, 6, 0)  # antes das 08:00
    assert fit_window(moment, "08:00", "23:00") == datetime(2026, 1, 1, 8, 0)


def test_fit_window_inside_stays_put() -> None:
    moment = datetime(2026, 1, 1, 14, 30)
    assert fit_window(moment, "08:00", "23:00") == moment


def test_fit_window_after_rolls_to_next_day_opening() -> None:
    moment = datetime(2026, 1, 1, 23, 30)  # depois das 23:00
    assert fit_window(moment, "08:00", "23:00") == datetime(2026, 1, 2, 8, 0)


def test_reword_stays_within_limit_and_nonempty() -> None:
    text = "Hoje eu quero muito sair com minha amiga a noite."
    out = reword(text, limit=280)
    assert out
    assert len(out) <= 280


def test_reword_untouched_text_passes_through() -> None:
    # Nenhuma palavra do dicionario: devolve o texto (so' aparado no limite).
    text = "xyzabc qwerty foobar"
    assert reword(text) == text


def test_parse_angles_well_formed_json() -> None:
    assert _parse_angles('["Angulo um", "Angulo dois"]', 3) == ["Angulo um", "Angulo dois"]


def test_parse_angles_truncated_json_recovers_valid_items() -> None:
    # JSON cortado no meio (modelo parou de gerar): falta a aspa/colchete final
    # do ultimo item. Deve recuperar so' os itens completos, nunca devolver o
    # blob cru com colchetes/aspas (bug real observado em producao).
    broken = '["Primeiro angulo completo", "Segundo tambem completo", "Terceiro cortado sem fechar]'
    result = _parse_angles(broken, 3)
    assert result == ["Primeiro angulo completo", "Segundo tambem completo"]
    assert all("[" not in a and not a.startswith('"') for a in result)


def test_parse_angles_plain_text_fallback() -> None:
    assert _parse_angles("Uma linha qualquer sem JSON", 1) == ["Uma linha qualquer sem JSON"]
