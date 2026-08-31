"""Analytics de posts publicados e otimizacao de horarios.

Logica pura — sem I/O, testavel isolada. Recebe linhas normalizadas
({published_at, likes, reposts, replies, views}) e devolve agregados e
sugestoes de horario. Nunca acessa banco nem navegador.

Fonte dos dados: `PostStats` — engajamento dos posts PUBLICADOS pela propria
conta, coletado pelo worker (`collect_post_stats`) via navegador, de graca
(perfil proprio, sem API oficial paga).

Como a otimizacao funciona
--------------------------
1. Agrega o engajamento por HORA do dia no fuso da conta.
2. Dá a cada hora um score com prior bayesiano: horas com pouca amostra sao
   puxadas para a media global em vez de virarem campeas por um unico post
   anomalo (o post "viral" de sorte nao domina o calendario).
3. `optimized_slots` escolhe as melhores horas dentro da janela de publicacao,
   respeitando o intervalo minimo, e materializa horarios concretos com offset
   determinístico por dia (sem aleatoriedade — mesma previsibilidade do
   distribute_slots).
4. Sem dados suficientes, devolve None e o chamador cai no `distribute_slots`
   (espalhamento uniforme) — otimizacao nunca trava o agendamento.
"""

from datetime import datetime, timedelta

# Mesmos pesos do scoring: repost sinaliza mais intencao que like.
LIKE_W, REPOST_W, REPLY_W = 1.0, 2.0, 1.5

# Prior bayesiano: abaixo de MIN_HOUR_SAMPLES posts por hora, o score da hora
# e' puxado para a media global. Regula horas com pouquissima amostra.
MIN_HOUR_SAMPLES = 3


def weighted_engagement(likes: int, reposts: int, replies: int) -> float:
    """Engajamento ponderado de um post. Views nao entram: sao pouco confiaveis
    na coleta via DOM (frequentemente 0) e a escala difere muito entre contas."""
    return likes * LIKE_W + reposts * REPOST_W + replies * REPLY_W


def hourly_aggregates(rows: list[dict], tz) -> dict[int, dict]:
    """Agrupa linhas por hora do dia (no fuso `tz`) somando as metricas.

    rows: [{"published_at": datetime, "likes": int, "reposts": int,
            "replies": int, "views": int}, ...]

    Retorna dict[0..23] = {"posts", "likes", "reposts", "replies", "views",
                           "weighted"}. Todas as 24 horas existem (zeradas).
    """
    agg = {
        h: {"posts": 0, "likes": 0, "reposts": 0, "replies": 0, "views": 0, "weighted": 0.0}
        for h in range(24)
    }
    for r in rows:
        dt = r["published_at"]
        if dt.tzinfo is None:
            raise ValueError("published_at precisa de timezone (tz-aware)")
        h = dt.astimezone(tz).hour
        bucket = agg[h]
        bucket["posts"] += 1
        bucket["likes"] += int(r.get("likes") or 0)
        bucket["reposts"] += int(r.get("reposts") or 0)
        bucket["replies"] += int(r.get("replies") or 0)
        bucket["views"] += int(r.get("views") or 0)
    for bucket in agg.values():
        bucket["weighted"] = weighted_engagement(
            bucket["likes"], bucket["reposts"], bucket["replies"]
        )
    return agg


def _global_prior(agg: dict[int, dict]) -> float:
    """Media global de engajamento ponderado por post (prior do score)."""
    posts = sum(b["posts"] for b in agg.values())
    weighted = sum(b["weighted"] for b in agg.values())
    return weighted / posts if posts else 0.0


def hour_score(bucket: dict, prior: float) -> float:
    """Score bayesiano da hora: media da hora amortecida pelo prior global.

    score = (weighted + prior * k) / (posts + k). Hora sem post nenhum tem
    score == prior (nao "campea" nem "perdedora" sem dado).
    """
    k = MIN_HOUR_SAMPLES
    return (bucket["weighted"] + prior * k) / (bucket["posts"] + k)


def window_hours(window_start: str, window_end: str) -> list[int]:
    """Horas inteiras cobertas pela janela "08:00"-"23:00" -> [8..23]."""
    sh, sm = (int(x) for x in window_start.split(":"))
    eh, em = (int(x) for x in window_end.split(":"))
    if not (0 <= sh <= 23 and 0 <= eh <= 23):
        raise ValueError("janela invalida")
    return list(range(sh, eh + 1))


def best_hours(
    agg: dict[int, dict],
    window_start: str,
    window_end: str,
    count: int,
    min_gap_minutes: int,
) -> list[int] | None:
    """Melhores horas de publicar, por engajamento historico.

    So horas com PELO MENOS um post competem (sem dado, sem recomendacao de
    dados). Espacamento minimo entre horas respeita min_gap_minutes. Retorna
    None quando nao ha dados suficientes — o chamador usa espalhamento.
    """
    prior = _global_prior(agg)
    scored = []
    for h in window_hours(window_start, window_end):
        if agg[h]["posts"] >= 1:
            scored.append((hour_score(agg[h], prior), h))
    if not scored:
        return None

    # Maior score primeiro; em empate, hora mais cedo (previsivel).
    scored.sort(key=lambda item: (-item[0], item[1]))
    gap_hours = max(1, (min_gap_minutes + 59) // 60)

    chosen: list[int] = []
    for _, h in scored:
        if all(abs(h - c) >= gap_hours for c in chosen):
            chosen.append(h)
        if len(chosen) >= count:
            break
    return sorted(chosen)


def optimized_slots(
    day: datetime,
    count: int,
    window_start: str,
    window_end: str,
    min_gap_minutes: int,
    agg: dict[int, dict],
    seed: int = 0,
) -> list[datetime] | None:
    """Horarios concretos de publicacao para `day`, guiados pelo engajamento.

    Escolhe as melhores horas (best_hours) e materializa um horario por hora
    com offset determinístico. Se faltar hora com dado, completa com as horas
    da janela ainda livres (com mais posts primeiro). Retorna None sem dados —
    o chamador cai no espalhamento uniforme.
    """
    if count <= 0:
        return []
    best = best_hours(agg, window_start, window_end, count, min_gap_minutes)
    if best is None:
        return None

    # Completa horas faltantes dentro da janela: prefere as com mais posts.
    gap_hours = max(1, (min_gap_minutes + 59) // 60)
    remaining_hours = [
        (agg[h]["posts"], h)
        for h in window_hours(window_start, window_end)
        if h not in best
    ]
    remaining_hours.sort(key=lambda item: (-item[0], item[1]))
    for _, h in remaining_hours:
        if len(best) >= count:
            break
        if all(abs(h - c) >= gap_hours for c in best):
            best.append(h)
    best = sorted(best[:count])

    sh, sm = (int(x) for x in window_start.split(":"))
    eh, em = (int(x) for x in window_end.split(":"))
    start = day.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = day.replace(hour=eh, minute=em, second=0, microsecond=0)

    slots: list[datetime] = []
    for i, h in enumerate(best):
        # Offset deterministico dentro da hora (funcao do dia e da posicao) —
        # sem aleatoriedade, mesmo espirito do distribute_slots.
        minute = 4 + ((seed * 7 + i * 17 + day.day * 13) % 52)
        slot = start.replace(hour=h, minute=minute)
        if slots and (slot - slots[-1]) < timedelta(minutes=min_gap_minutes):
            slot = slots[-1] + timedelta(minutes=min_gap_minutes)
        if slot > end:
            continue
        slots.append(slot)
    return slots
