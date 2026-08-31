"""Distribuicao igualitaria de posts entre contas (logica pura, testavel).

Regra de negocio: N posts divididos entre M contas de forma PARELHA — com 30
posts e 3 contas, cada conta fica com 10. Cada item e' atribuido UMA vez
(round-robin), entao o mesmo post nunca cai em duas contas por construcao.
"""


def round_robin_assign(items: list, targets: list) -> list[tuple]:
    """Atribui cada item a um alvo, ciclando entre os alvos.

    items=[p1..p5], targets=[A, B, C] -> [(p1,A), (p2,B), (p3,C), (p4,A), (p5,B)].
    Levanta se nao houver alvo (nao faz sentido distribuir no vazio).
    """
    if not targets:
        raise ValueError("precisa de pelo menos um alvo")
    if not items:
        return []
    return [(item, targets[i % len(targets)]) for i, item in enumerate(items)]


def count_per_target(assignments: list[tuple], key) -> dict:
    """Conta atribuicoes por alvo usando `key` (ex: lambda t: t.username)."""
    counts: dict = {}
    for _item, target in assignments:
        k = key(target)
        counts[k] = counts.get(k, 0) + 1
    return counts
