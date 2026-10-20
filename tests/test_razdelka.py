from decimal import Decimal as D

import pytest

from rpa1c.razdelka import Row, calc_shares

CHICKEN = [
    Row("Окорочок", D("1.6"), D("310")),
    Row("Грудка", D("1.5"), D("410")),
    Row("Суповой набор", D("0.9"), D("49")),
]


def test_kttsb_004740():
    assert calc_shares(CHICKEN) == [
        (D("0.400"), D("0.43")), (D("0.375"), D("0.53")), (D("0.225"), D("0.04"))]


def test_single_row():
    assert calc_shares([Row("x", D("5"))]) == [(D(1), D(1))]


def test_waste_gets_zero_cost_share():
    rows = CHICKEN + [Row("Свинина ОТХОДЫ", D("0.5"), D("100"), waste=True)]
    res = calc_shares(rows)
    assert res[-1][1] == 0
    assert sum(r[0] for r in res) == D("1.000")
    assert sum(r[1] for r in res) == D("1.00")


def test_rounding_remainder_goes_to_max_row_first_on_tie():
    rows = [Row("a", D(1), D(1)), Row("b", D(1), D(1)), Row("c", D(1), D(1))]
    res = calc_shares(rows)
    assert [r[0] for r in res] == [D("0.334"), D("0.333"), D("0.333")]
    assert [r[1] for r in res] == [D("0.34"), D("0.33"), D("0.33")]


def test_cost_remainder_to_largest_weight():
    # 0.99 -> недостающее 0.01 уходит строке с наибольшим весом
    rows = [Row("a", D(1), D(1)), Row("b", D(1), D(1)), Row("big", D(1), D(1))]
    assert sum(r[1] for r in calc_shares(rows)) == D("1.00")


def test_min_share_taken_from_largest_weight():
    rows = [Row("мясо", D(10), D(300)), Row("кость", D("0.1"), D(10))]
    assert calc_shares(rows)[1][1] == D("0.00")
    res = calc_shares(rows, D("0.01"))
    assert res[1][1] == D("0.01") and res[0][1] == D("0.99")


def test_no_priced_rows_is_error():
    with pytest.raises(ValueError):
        calc_shares([Row("a", D(1), waste=True), Row("b", D(1), waste=True)])
