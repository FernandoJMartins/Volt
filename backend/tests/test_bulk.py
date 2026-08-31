"""Testes da distribuicao igualitaria de posts entre contas."""

import pytest

from app.services.bulk import count_per_target, round_robin_assign


def test_round_robin_divide_parelho():
    # 30 posts, 3 contas -> 10 por conta.
    items = list(range(30))
    targets = ["A", "B", "C"]
    assignments = round_robin_assign(items, targets)
    counts = count_per_target(assignments, lambda t: t)
    assert counts == {"A": 10, "B": 10, "C": 10}
    # Cada item aparece UMA vez (nenhum post cai em duas contas).
    assert sorted(i for i, _ in assignments) == items


def test_round_robin_resto_vai_para_as_primeiras_contas():
    # 5 posts, 3 contas -> 2/2/1.
    assignments = round_robin_assign(list(range(5)), ["A", "B", "C"])
    assert count_per_target(assignments, lambda t: t) == {"A": 2, "B": 2, "C": 1}


def test_round_robin_sem_alvo_levanta():
    with pytest.raises(ValueError):
        round_robin_assign([1, 2, 3], [])


def test_round_robin_lista_vazia():
    assert round_robin_assign([], ["A"]) == []
