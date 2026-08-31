"""Testes da extracao/limpeza de urls de midia de posts coletados (Fase 5+)."""

from app.services.sources import clamp_collect_count
from app.services.x_web import dedup_media_urls


def test_dedup_media_urls_remove_mesma_midia_em_resolucoes_diferentes():
    urls = [
        "https://pbs.twimg.com/media/A1?format=jpg&name=small",
        "https://pbs.twimg.com/media/A1?format=jpg&name=medium",
        "https://pbs.twimg.com/media/B2?format=png&name=900x900",
    ]
    out = dedup_media_urls(urls)
    assert out == [urls[0], urls[2]]  # A1 deduplicada (mesma base), B2 preservada


def test_dedup_media_urls_respeita_limite_e_ordem():
    urls = [f"https://pbs.twimg.com/media/M{i}?format=jpg" for i in range(6)]
    out = dedup_media_urls(urls, limit=4)
    assert out == urls[:4]


def test_dedup_media_urls_lista_vazia():
    assert dedup_media_urls([]) == []


def test_clamp_collect_count_limita_ao_teto():
    assert clamp_collect_count(None) == 15
    assert clamp_collect_count(50) == 50
    assert clamp_collect_count(500) == 100
    assert clamp_collect_count(0) == 1
    assert clamp_collect_count(-3) == 1
