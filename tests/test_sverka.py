from rpa1c.sverka import reconcile, subset_sum


def L(doc, key, qty, num=None):
    return {"doc": doc, "num": num or doc, "date": "01.01.2026", "key": key, "qty": qty}


def by_doc(results):
    return {r.doc: r for r in results}


def test_exact_match_full():
    ret = [L("В1", "мол|с1|п", 5)]
    corr = [L("К1", "мол|с1|п", 5)]
    rr, cr = reconcile(ret, corr)
    assert rr[0].status == "full" and cr[0].status == "full"


def test_combination_of_returns_closes_one_correction_line():
    ret = [L("В1", "мол|с1|п", 3), L("В2", "мол|с1|п", 2), L("В3", "мол|с1|п", 10)]
    corr = [L("К1", "мол|с1|п", 5)]
    rr, cr = reconcile(ret, corr)
    r = by_doc(rr)
    assert r["В1"].status == "full" and r["В2"].status == "full"
    assert r["В3"].status == "none"
    assert cr[0].status == "full"


def test_return_with_three_lines_one_correction_is_partial():
    ret = [L("В1", "а|с|п", 1), L("В1", "б|с|п", 2), L("В1", "в|с|п", 3)]
    corr = [L("К1", "а|с|п", 1)]
    rr, _ = reconcile(ret, corr)
    assert rr[0].status == "partial" and rr[0].n_matched == 1 and rr[0].n_total == 3


def test_supplier_is_part_of_key():
    ret = [L("В1", "мол|с1|поставщик1", 5)]
    corr = [L("К1", "мол|с1|поставщик2", 5)]
    rr, cr = reconcile(ret, corr)
    assert rr[0].status == "none" and cr == []  # корректировка нерелевантна


def test_return_not_deletable_while_correction_not_closed_fully():
    # возврат закрыт полностью, но корректировка закрывает только одну из двух своих позиций
    ret = [L("В1", "а|с|п", 1)]
    corr = [L("К1", "а|с|п", 1), L("К1", "б|с|п", 4)]
    rr, cr = reconcile(ret, corr)
    assert cr[0].status == "partial"
    assert rr[0].status == "partial" and rr[0].corr_not_ready == ["К1"]


def test_optimizer_prefers_correction_that_closes_more_return_lines():
    # единственную строку возврата «а» могут закрыть и малая (1 строка), и большая корректировка (2 строки);
    # выгоднее большая: закрываются обе позиции возврата, а не одна
    ret = [L("В1", "а|с|п", 5), L("В2", "б|с|п", 7)]
    corr = [L("К_большая", "а|с|п", 5), L("К_большая", "б|с|п", 7),
            L("К_малая", "а|с|п", 5)]
    rr, cr = reconcile(ret, corr)
    c = by_doc(cr)
    assert c["К_большая"].status == "full"
    assert c["К_малая"].status == "none"
    assert all(r.status == "full" for r in rr)


def test_optimizer_prefers_more_closed_corrections_at_equal_coverage():
    # возвраты 3 и 2; корректировка К1 (5) закрылась бы суммой 3+2, но К2 (3) и К3 (2) закрывают те же позиции
    # двумя документами — закрыто больше корректировок
    ret = [L("В1", "а|с|п", 3), L("В2", "а|с|п", 2)]
    corr = [L("К1", "а|с|п", 5), L("К2", "а|с|п", 3), L("К3", "а|с|п", 2)]
    rr, cr = reconcile(ret, corr)
    c = by_doc(cr)
    assert c["К2"].status == "full" and c["К3"].status == "full" and c["К1"].status == "none"


def test_optimizer_covers_all_return_lines_when_possible():
    # корректировка К1 закрывает 3 и 2 (комбинация), К2 закрывает 5 одной строкой: все три позиции возврата закрыты
    ret = [L("В1", "а|с|п", 3), L("В2", "а|с|п", 2), L("В3", "а|с|п", 5)]
    corr = [L("К1", "а|с|п", 5), L("К2", "а|с|п", 5)]
    rr, cr = reconcile(ret, corr)
    assert all(r.status == "full" for r in rr)


def test_tolerance():
    ret = [L("В1", "а|с|п", 5.004)]
    corr = [L("К1", "а|с|п", 5)]
    assert reconcile(ret, corr, tol=0.01)[0][0].status == "full"
    ret = [L("В1", "а|с|п", 5.004)]
    corr = [L("К1", "а|с|п", 5)]
    assert reconcile(ret, corr, tol=0.001)[0][0].status == "none"


def test_max_combo_limits_combination():
    pool = [{"qty": 1.0, "idx": i} for i in range(5)]
    assert subset_sum(pool, 5, 0.001, 5) is not None
    assert subset_sum(pool, 5, 0.001, 4) is None


def test_return_line_used_once():
    ret = [L("В1", "а|с|п", 5)]
    corr = [L("К1", "а|с|п", 5), L("К2", "а|с|п", 5)]
    rr, cr = reconcile(ret, corr)
    c = by_doc(cr)
    assert sorted(x.status for x in c.values()) == ["full", "none"]


# ── этап 2: цепочки корректировок ──
from datetime import datetime as _dt
from rpa1c.sverka import plan_chain, new_doc_date


def _k(num, d, posted=False):
    return {"num": num, "date": d, "posted": posted}


def test_new_date_keeps_time_of_day():
    assert new_doc_date(_dt(2026, 6, 10, 11, 30), _dt(2026, 10, 23)) == _dt(2026, 10, 23, 11, 30)
    same = _dt(2026, 10, 23, 9, 5)
    assert new_doc_date(same, _dt(2026, 10, 23)) is same


def test_chain_posts_in_order_and_refills_all_but_first():
    items = [_k("К1", _dt(2026, 6, 10, 9)), _k("К2", _dt(2026, 6, 11, 9)), _k("К3", _dt(2026, 6, 12, 9))]
    sel = {n: _dt(2026, 10, 23) for n in ("К1", "К2", "К3")}
    # все три на одну дату: порядок сохраняется только если время суток возрастает — здесь нет (9:00 везде)
    log = plan_chain(items, sel)
    # одна дата и одинаковое время суток: каждая следующая ставится на секунду позже предыдущей
    assert [r["ok"] for r in log] == [True, True, True]
    assert [r["date"] for r in log] == [_dt(2026, 10, 23, 9), _dt(2026, 10, 23, 9, 0, 1), _dt(2026, 10, 23, 9, 0, 2)]
    items = [_k("К1", _dt(2026, 6, 10, 9)), _k("К2", _dt(2026, 6, 11, 10)), _k("К3", _dt(2026, 6, 12, 11))]
    log = plan_chain(items, sel)
    assert [r["ok"] for r in log] == [True, True, True]
    assert [r["refill"] for r in log] == [False, True, True]


def test_first_correction_refilled_when_earlier_is_already_posted():
    items = [_k("К1", _dt(2026, 6, 10, 9), True), _k("К2", _dt(2026, 6, 11, 9))]
    log = plan_chain(items, {"К2": _dt(2026, 6, 11)})
    assert log[0]["refill"] is True and log[0]["ok"] is True


def test_unselected_unposted_blocks_following():
    items = [_k("К1", _dt(2026, 6, 10, 9)), _k("К2", _dt(2026, 6, 11, 9)), _k("К3", _dt(2026, 6, 12, 9))]
    log = plan_chain(items, {"К2": _dt(2026, 6, 11), "К3": _dt(2026, 6, 12)})
    assert [r["ok"] for r in log] == [False, None]
    assert "К1" in log[0]["msg"]


def test_date_must_be_after_previous_posted():
    items = [_k("К1", _dt(2026, 10, 1, 9), True), _k("К2", _dt(2026, 6, 11, 9))]
    log = plan_chain(items, {"К2": _dt(2026, 6, 11)})
    assert log[0]["ok"] is False


def test_dry_run_does_not_refill_after_virtual_posting():
    items = [_k("К1", _dt(2026, 6, 10, 9)), _k("К2", _dt(2026, 6, 11, 9))]
    sel = {"К1": _dt(2026, 6, 10), "К2": _dt(2026, 6, 11)}
    log = plan_chain(items, sel, dry_run=True)
    assert [r["refill"] for r in log] == [False, False]
    assert [r["ok"] for r in log] == [None, None]


def test_same_day_time_order_is_fixed_by_bumping_seconds():
    # К1 в 15:00, К2 в 09:00 следующего дня; обе переносим на один день -> К2 после К1
    items = [_k("К1", _dt(2026, 6, 10, 15)), _k("К2", _dt(2026, 6, 11, 9))]
    sel = {"К1": _dt(2026, 10, 23), "К2": _dt(2026, 10, 23)}
    log = plan_chain(items, sel)
    assert log[1]["ok"] is True and log[1]["date"] == _dt(2026, 10, 23, 15, 0, 1)


def test_day_before_previous_still_error():
    items = [_k("К1", _dt(2026, 10, 24, 9), True), _k("К2", _dt(2026, 6, 11, 9))]
    log = plan_chain(items, {"К2": _dt(2026, 10, 23)})
    assert log[0]["ok"] is False


def test_include_previous_adds_unselected_earlier_corrections():
    items = [_k("К1", _dt(2026, 6, 10, 9)), _k("К2", _dt(2026, 6, 11, 9)), _k("К3", _dt(2026, 6, 12, 9))]
    sel = {"К3": _dt(2026, 10, 23)}
    log = plan_chain(items, sel, include_previous=True, default_day=_dt(2026, 10, 23))
    assert [r["num"] for r in log] == ["К1", "К2", "К3"]
    assert [r["ok"] for r in log] == [True, True, True]
    assert [r["msg"] for r in log] == ["added", "added", ""]
    assert [r["refill"] for r in log] == [False, True, True]
    assert log[0]["date"] < log[1]["date"] < log[2]["date"]


def test_include_previous_does_not_add_later_unselected():
    items = [_k("К1", _dt(2026, 6, 10, 9)), _k("К2", _dt(2026, 6, 11, 9))]
    log = plan_chain(items, {"К1": _dt(2026, 10, 23)}, include_previous=True, default_day=_dt(2026, 10, 23))
    assert [r["num"] for r in log] == ["К1"]


# ── совместимость по поступлению ──
def test_correction_of_later_purchase_is_not_matched_to_earlier_return():
    # возврат 2025 года и корректировка к поступлению 2026 года не могут быть парой
    ret = [dict(L("В1", "мол|с1|п", 1), date=_dt(2025, 6, 12))]
    corr = [dict(L("К1", "мол|с1|п", 1), base="ПТУ-2026", base_date=_dt(2026, 6, 12))]
    rr, cr = reconcile(ret, corr)
    assert rr[0].status == "none" and cr == []


def test_purchase_in_return_must_equal_correction_base():
    ret = [dict(L("В1", "мол|с1|п", 1), date=_dt(2026, 7, 1), purchase="ПТУ-А")]
    corr = [dict(L("К1", "мол|с1|п", 1), base="ПТУ-Б", base_date=_dt(2026, 6, 1))]
    assert reconcile(ret, corr)[0][0].status == "none"
    corr = [dict(L("К1", "мол|с1|п", 1), base="ПТУ-А", base_date=_dt(2026, 6, 1))]
    assert reconcile(ret, corr)[0][0].status == "full"


def test_earlier_purchase_without_explicit_link_is_matched():
    ret = [dict(L("В1", "мол|с1|п", 1), date=_dt(2026, 7, 1))]
    corr = [dict(L("К1", "мол|с1|п", 1), base="ПТУ", base_date=_dt(2026, 6, 1))]
    assert reconcile(ret, corr)[0][0].status == "full"


# ── срок корректировки: не раньше возврата, не позже 3 месяцев ──
def test_correction_slightly_before_return_is_matched_return_posted_late():
    # возврат провели позже прихода корректировки: корректировка на 5 дней раньше возврата — допустимо
    ret = [dict(L("В1", "а|с|п", 1), date=_dt(2026, 6, 10))]
    corr = [dict(L("К1", "а|с|п", 1), corr_date=_dt(2026, 6, 5))]
    assert reconcile(ret, corr)[0][0].status == "full"


def test_correction_much_earlier_than_return_is_not_matched():
    ret = [dict(L("В1", "а|с|п", 1), date=_dt(2026, 6, 10))]
    corr = [dict(L("К1", "а|с|п", 1), corr_date=_dt(2026, 5, 1))]   # на 40 дней раньше, допуск 30
    assert reconcile(ret, corr)[0][0].status == "none"


def test_explicit_purchase_link_waives_lower_date_bound():
    ret = [dict(L("В1", "а|с|п", 1), date=_dt(2026, 6, 10), purchase="ПТУ-А")]
    corr = [dict(L("К1", "а|с|п", 1), corr_date=_dt(2026, 4, 1), base="ПТУ-А", base_date=_dt(2026, 3, 1))]
    assert reconcile(ret, corr)[0][0].status == "full"


def test_correction_within_three_months_is_matched_and_after_is_not():
    ret = [dict(L("В1", "а|с|п", 1), date=_dt(2026, 6, 10, 15))]
    ok = [dict(L("К1", "а|с|п", 1), corr_date=_dt(2026, 9, 10, 8))]       # ровно 3 месяца (по дням)
    late = [dict(L("К1", "а|с|п", 1), corr_date=_dt(2026, 9, 11))]
    assert reconcile(ret, ok)[0][0].status == "full"
    ret = [dict(L("В1", "а|с|п", 1), date=_dt(2026, 6, 10, 15))]
    assert reconcile(ret, late)[0][0].status == "none"


def test_purchase_must_be_before_return():
    ret = [dict(L("В1", "а|с|п", 1), date=_dt(2026, 6, 10))]
    corr = [dict(L("К1", "а|с|п", 1), corr_date=_dt(2026, 6, 20), base_date=_dt(2026, 6, 12))]
    assert reconcile(ret, corr)[0][0].status == "none"
    ret = [dict(L("В1", "а|с|п", 1), date=_dt(2026, 6, 10))]
    corr = [dict(L("К1", "а|с|п", 1), corr_date=_dt(2026, 6, 20), base_date=_dt(2026, 6, 1))]
    assert reconcile(ret, corr)[0][0].status == "full"


def test_large_group_finishes_within_time_budget():
    import random, time
    random.seed(1)
    ret = [L("R%d" % (i // 3), "a|s|p", random.choice([1, 2, 3, 5])) for i in range(60)]
    corr = []
    for k in range(40):
        for _ in range(random.choice([1, 2, 3])):
            corr.append(L("K%d" % k, "a|s|p", random.choice([1, 2, 3, 5, 6, 8])))
    t0 = time.time()
    rr, cr = reconcile(ret, corr, time_limit=0.5)
    assert time.time() - t0 < 5          # не зависает: время ограничено, результат не хуже жадного
    assert any(r.status == "full" for r in rr)
