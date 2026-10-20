"""Эталонная реализация расчёта долей для документа «Разделка».

Зеркалит BSL-модуль 1c_extension/РазделкаДоли.bsl: те же шаги, то же округление
(half-up, как Окр(...,N,1) в 1С). Нужна для тестов на данных Excel за июль–октябрь.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

OUT_Q = Decimal("0.001")
COST_Q = Decimal("0.01")


@dataclass
class Row:
    name: str
    fact: Decimal
    price: Decimal = Decimal(0)
    waste: bool = False


def _r(x: Decimal, q: Decimal) -> Decimal:
    return x.quantize(q, rounding=ROUND_HALF_UP)


def _first_max(values) -> int:
    best = 0
    for i, v in enumerate(values):
        if v > values[best]:  # строгое > : при равенстве остаётся первая
            best = i
    return best


def calc_shares(rows, min_share: Decimal = Decimal(0)):
    """Возвращает [(доля_выхода, доля_сс)] в порядке строк."""
    if not rows:
        return []
    if len(rows) == 1:
        return [(Decimal(1), Decimal(1))]

    total_fact = sum((r.fact for r in rows), Decimal(0))
    if total_fact <= 0:
        raise ValueError("Сумма фактического количества должна быть больше нуля")

    out = [_r(r.fact / total_fact, OUT_Q) for r in rows]
    out[_first_max([r.fact for r in rows])] += Decimal(1) - sum(out)

    weights = [Decimal(0) if r.waste else r.fact * r.price for r in rows]
    total_w = sum(weights)
    if total_w <= 0:
        raise ValueError("Нет продаваемых позиций с ценой: доли себестоимости не рассчитать")

    cost = [_r(w / total_w, COST_Q) for w in weights]
    imax = _first_max(weights)
    cost[imax] += Decimal(1) - sum(cost)

    if min_share > 0:
        for i, w in enumerate(weights):
            if w > 0 and cost[i] == 0:
                cost[i] = min_share
                cost[_first_max(weights)] -= min_share  # у строки с наибольшим весом

    return list(zip(out, cost))
