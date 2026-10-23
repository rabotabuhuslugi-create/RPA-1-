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


def test_small_documents_first_dont_lose_returns():
    # К_малая (1 строка) должна получить возврат до крупной К_большая
    ret = [L("В1", "а|с|п", 5), L("В2", "б|с|п", 7)]
    corr = [L("К_большая", "а|с|п", 5), L("К_большая", "б|с|п", 7),
            L("К_малая", "а|с|п", 5)]
    rr, cr = reconcile(ret, corr)
    c = by_doc(cr)
    assert c["К_малая"].status == "full"
    assert c["К_большая"].status == "partial"


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
