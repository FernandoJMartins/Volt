"""Distribuicao de horarios de publicacao. Logica pura — sem I/O, testavel isolada."""

from datetime import datetime, timedelta


def fit_window(moment: datetime, window_start: str, window_end: str) -> datetime:
    """Empurra `moment` pra dentro da janela [window_start, window_end) do MESMO dia.

    Antes da janela -> abertura do dia. Depois -> abertura do dia seguinte.
    """
    sh, sm = (int(x) for x in window_start.split(":"))
    eh, em = (int(x) for x in window_end.split(":"))
    start = moment.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = moment.replace(hour=eh, minute=em, second=0, microsecond=0)

    if moment < start:
        return start
    if moment > end:
        return (start + timedelta(days=1)).replace(hour=sh, minute=sm)
    return moment


def distribute_slots(
    day: datetime,
    count: int,
    window_start: str,
    window_end: str,
    min_gap_minutes: int,
    seed: int = 0,
) -> list[datetime]:
    """Espalha `count` horarios pela janela do dia respeitando o intervalo minimo.

    Divide a janela em blocos iguais e desloca o horario dentro de cada bloco de forma
    DETERMINISTICA (funcao do seed e do dia). Nao é aleatoriedade para enganar antispam —
    serve so para o feed nao ficar rigido tipo 08:00, 09:00, 10:00.
    """
    sh, sm = (int(x) for x in window_start.split(":"))
    eh, em = (int(x) for x in window_end.split(":"))
    start = day.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = day.replace(hour=eh, minute=em, second=0, microsecond=0)

    total_minutes = int((end - start).total_seconds() / 60)
    if total_minutes <= 0 or count <= 0:
        return []

    # Nunca gera mais posts do que o intervalo minimo permite (guarda-corpo anti-spam).
    max_by_gap = total_minutes // max(min_gap_minutes, 1) + 1
    count = min(count, max_by_gap)
    block = total_minutes / count

    slots: list[datetime] = []
    for i in range(count):
        offset_ratio = 0.15 + (((seed * 7 + i * 31 + day.day * 13) % 70) / 100.0)
        minute = int(i * block + block * offset_ratio)
        slot = start + timedelta(minutes=minute)
        if slots and (slot - slots[-1]).total_seconds() / 60 < min_gap_minutes:
            slot = slots[-1] + timedelta(minutes=min_gap_minutes)
        if slot <= end:
            slots.append(slot)
    return slots
