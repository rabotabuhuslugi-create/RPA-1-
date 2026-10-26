"""Эталон алгоритма сверки «Возврат поставщику ↔ Корректировка приобретения».

Точный порт логики из HTML-инструмента (reconcile/subsetSum) и из BSL-обработки
1c/СверкаВозвратов/. При правке алгоритма меняем ОБА места и гоняем tests/test_sverka.py.

Строка — словарь: doc (ключ документа), num, date, key (номенклатура|склад|поставщик), qty.
"""
from __future__ import annotations

from dataclasses import dataclass, field

LIMIT_STEPS = 200000  # защита от «взрыва» перебора, то же значение в BSL


def subset_sum(pool, target, tol, max_len):
    """Первая найденная комбинация строк пула с суммой количества == target (±tol).

    Пул сортируется по убыванию количества, при равенстве — по порядку появления (idx).
    """
    srt = sorted(pool, key=lambda r: (-r["qty"], r["idx"]))
    n = len(srt)
    suffix = [0.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix[i] = suffix[i + 1] + srt[i]["qty"]
    ctx = {"found": None, "steps": 0}

    def dfs(i, remaining, chosen):
        if ctx["found"] is not None or ctx["steps"] > LIMIT_STEPS:
            return
        ctx["steps"] += 1
        if len(chosen) > max_len:
            return
        if abs(remaining) <= tol:
            ctx["found"] = list(chosen)
            return
        if i >= n or remaining < -tol:
            return
        if remaining - tol > suffix[i]:
            return
        chosen.append(srt[i])
        dfs(i + 1, remaining - srt[i]["qty"], chosen)
        chosen.pop()
        if ctx["found"] is not None:
            return
        dfs(i + 1, remaining, chosen)

    dfs(0, target, [])
    return ctx["found"]


def _add_months(d, months):
    import calendar
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))


def compatible(ret, corr, max_months=3, early_days=30):
    """Можно ли сопоставлять строку возврата и строку корректировки.

    1. Срок: дата корректировки поставщика ("corr_date") не позже max_months месяцев после возврата ("date") и не раньше
       возврата более чем на early_days дней (возврат могут провести позже прихода корректировки);
       если в возврате явно указано то же поступление ("purchase" == "base"), нижняя граница не применяется.
    2. Поступление корректировки ("base_date") не позже возврата.
    3. Если в возврате указано поступление ("purchase") — оно должно совпасть с основанием корректировки ("base").
    Отсутствующие поля не ограничивают."""
    explicit = bool(ret.get("purchase")) and ret["purchase"] == corr.get("base")
    rd, cd = ret.get("date"), corr.get("corr_date")
    if rd is not None and cd is not None:
        r0 = rd.replace(hour=0, minute=0, second=0, microsecond=0)
        c0 = cd.replace(hour=0, minute=0, second=0, microsecond=0)
        if c0 > _add_months(r0, max_months):
            return False
        if not explicit and c0 < r0 - timedelta(days=early_days):
            return False
    bd = corr.get("base_date")
    if bd is not None and rd is not None and bd > rd:
        return False
    if ret.get("purchase"):
        return explicit
    return True


def _find(avail, line, tol, max_combo):
    if not avail:
        return None
    for r in avail:
        if abs(r["qty"] - line["qty"]) <= tol:
            return [r]
    combo = subset_sum(avail, line["qty"], tol, max_combo)
    return combo if combo else None



LIMIT_OPTIONS = 8        # вариантов раскладки одной строки корректировки
LIMIT_COMBO_STEPS = 3000


def _all_combos(pool, target, tol, max_len):
    """Все комбинации из 2+ строк пула с суммой target (±tol), не более LIMIT_OPTIONS."""
    srt = sorted(pool, key=lambda r: (-r["qty"], r["idx"]))
    n = len(srt)
    suffix = [0.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix[i] = suffix[i + 1] + srt[i]["qty"]
    out, steps = [], [0]

    def dfs(i, remaining, chosen):
        if len(out) >= LIMIT_OPTIONS or steps[0] > LIMIT_COMBO_STEPS:
            return
        steps[0] += 1
        if len(chosen) > max_len:
            return
        if abs(remaining) <= tol and len(chosen) >= 2:
            out.append(list(chosen))
            return
        if i >= n or remaining < -tol or remaining - tol > suffix[i]:
            return
        chosen.append(srt[i])
        dfs(i + 1, remaining - srt[i]["qty"], chosen)
        chosen.pop()
        dfs(i + 1, remaining, chosen)

    dfs(0, target, [])
    return out


def _line_options(rb, line, used, tol, max_combo, max_months, early_days):
    """Варианты закрыть строку корректировки свободными строками возврата: сначала одна строка, затем комбинации."""
    free = [r for r in rb.get(line["key"], [])
            if r["idx"] not in used and compatible(r, line, max_months, early_days)]
    opts = [[r] for r in free if abs(r["qty"] - line["qty"]) <= tol][:LIMIT_OPTIONS]
    if len(opts) < LIMIT_OPTIONS:
        opts += _all_combos(free, line["qty"], tol, max_combo)[:LIMIT_OPTIONS - len(opts)]
    return opts


def _components(docs, rb, max_months, early_days):
    """Корректировки, делящие хотя бы одну возможную строку возврата, попадают в одну компоненту."""
    parent = list(range(len(docs)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner = {}
    for i, d in enumerate(docs):
        for line in d["lines"]:
            for r in rb.get(line["key"], []):
                if compatible(r, line, max_months, early_days):
                    if r["idx"] in owner:
                        a, b = find(i), find(owner[r["idx"]])
                        if a != b:
                            parent[max(a, b)] = min(a, b)
                    else:
                        owner[r["idx"]] = i
    groups = {}
    for i in range(len(docs)):
        groups.setdefault(find(i), []).append(docs[i])
    return list(groups.values())


def greedy_component(docs, rb, tol, max_combo, max_months=3, early_days=30):
    """Быстрое жадное решение: документы по порядку, документ закрываем только если ВСЕ его строки нашли пару.
    Возвращает (assign, score) — стартовый вариант для точного подбора."""
    used, assign, score = set(), {}, 0
    for i, d in enumerate(docs):
        tentative, pairs, all_ok, nlines = set(), [], True, 0
        for line in d["lines"]:
            avail = [r for r in rb.get(line["key"], [])
                     if r["idx"] not in used and r["idx"] not in tentative and compatible(r, line, max_months, early_days)]
            found = _find(avail, line, tol, max_combo)
            if not found:
                all_ok = False
                break
            tentative.update(r["idx"] for r in found)
            pairs.append((line, found))
            nlines += len(found)
        if all_ok:
            used |= tentative
            assign[i] = pairs
            score += nlines * 1000 + 1
    return assign, score


def solve_component(docs, rb, tol, max_combo, max_months=3, early_days=30, time_limit=None, step_limit=300000):
    """Подбор: какие документы корректировки закрыть ЦЕЛИКОМ и какими строками возврата, чтобы закрыть как можно
    больше строк возврата (при равенстве — больше документов, затем раньше по порядку).
    Стартует с жадного решения и улучшает его точным перебором, пока не вышло время (time_limit, сек) или шаги.
    Возвращает {индекс документа: [(строка корректировки, [строки возврата])]}."""
    import time as _time
    deadline = None if time_limit is None else _time.monotonic() + time_limit
    n = len(docs)
    potential = [0] * (n + 1)
    acc = set()
    for i in range(n - 1, -1, -1):
        for line in docs[i]["lines"]:
            for r in rb.get(line["key"], []):
                if compatible(r, line, max_months, early_days):
                    acc.add(r["idx"])
        potential[i] = len(acc) * 1000 + (n - i)
    g_assign, g_score = greedy_component(docs, rb, tol, max_combo, max_months, early_days)
    best = {"score": g_score, "assign": g_assign}
    if g_score >= potential[0]:
        return best["assign"]
    steps = [0]
    stop = [False]
    assign = {}
    used = set()

    def out_of_budget():
        if stop[0]:
            return True
        if steps[0] > step_limit or (deadline is not None and steps[0] % 20 == 0 and _time.monotonic() > deadline):
            stop[0] = True
        return stop[0]

    def doc_search(i, score):
        if stop[0]:
            return
        if i >= n:
            if score > best["score"]:
                best["score"], best["assign"] = score, dict(assign)
            return
        if score + potential[i] <= best["score"]:
            return
        lines_search(i, 0, score, [], 0)
        if not stop[0]:
            doc_search(i + 1, score)

    def lines_search(i, k, score, pairs, nlines):
        steps[0] += 1
        if out_of_budget():
            return
        d = docs[i]
        if k >= len(d["lines"]):
            assign[i] = list(pairs)
            doc_search(i + 1, score + nlines * 1000 + 1)
            assign.pop(i, None)
            return
        line = d["lines"][k]
        for opt in _line_options(rb, line, used, tol, max_combo, max_months, early_days):
            if stop[0]:
                break
            for r in opt:
                used.add(r["idx"])
            pairs.append((line, opt))
            lines_search(i, k + 1, score, pairs, nlines + len(opt))
            pairs.pop()
            for r in opt:
                used.discard(r["idx"])

    doc_search(0, 0)
    return best["assign"]


@dataclass
class DocResult:
    doc: str
    num: str
    date: str
    status: str  # full | partial | none
    n_matched: int
    n_total: int
    lines: list = field(default_factory=list)  # [(line, [другие строки] | None)]
    corr_not_ready: list = field(default_factory=list)


def reconcile(ret_all, corr_all, tol=0.01, max_combo=6, max_months=3, early_days=30, time_limit=20):
    for i, r in enumerate(ret_all):
        r["idx"] = i
    for i, c in enumerate(corr_all):
        c["idx"] = i

    rb = {}
    for r in ret_all:
        rb.setdefault(r["key"], []).append(r)

    doc_order, doc_map = [], {}
    for c in corr_all:
        if c["doc"] not in doc_map:
            doc_map[c["doc"]] = []
            doc_order.append(c["doc"])
        doc_map[c["doc"]].append(c)

    docs = []
    for dk in doc_order:
        lines = doc_map[dk]
        docs.append({
            "doc": dk, "num": lines[0]["num"], "date": lines[0]["date"], "lines": lines,
            "relevant": any(compatible(r, l, max_months, early_days) for l in lines for r in rb.get(l["key"], [])), "resolved": False,
        })

    used = set()
    line_match = {}   # idx строки корректировки -> [строки возврата]
    ret_to_corr = {}  # idx строки возврата -> (строка корректировки, соседи)

    def commit(line, found):
        line_match[line["idx"]] = found
        for r in found:
            used.add(r["idx"])
            ret_to_corr[r["idx"]] = (line, found)

    candidates = sorted((d for d in docs if d["relevant"]), key=lambda d: (len(d["lines"]), d["doc"]))

    # Раунд 1: точный подбор по компонентам — закрыть ЦЕЛИКОМ те документы корректировки, которые дают
    # максимум закрытых строк возврата (а не «первые подошедшие»)
    for comp in _components(candidates, rb, max_months, early_days):
        solution = solve_component(comp, rb, tol, max_combo, max_months, early_days, time_limit)
        for i, pairs in solution.items():
            for line, found in pairs:
                commit(line, found)
            comp[i]["resolved"] = True

    # Раунд 2: частичные совпадения для остальных
    for d in candidates:
        if d["resolved"]:
            continue
        for line in d["lines"]:
            if line["idx"] in line_match:
                continue
            avail = [r for r in rb.get(line["key"], []) if r["idx"] not in used and compatible(r, line, max_months, early_days)]
            found = _find(avail, line, tol, max_combo)
            if found:
                commit(line, found)

    def status_of(n_matched, n_total):
        return "full" if n_matched == n_total else ("partial" if n_matched > 0 else "none")

    corr_results = []
    for d in docs:
        if not d["relevant"]:
            continue
        info = [(l, line_match.get(l["idx"])) for l in d["lines"]]
        nm = sum(1 for _, m in info if m)
        corr_results.append(DocResult(d["doc"], d["num"], d["date"], status_of(nm, len(info)), nm, len(info), info))
    corr_by_doc = {c.doc: c for c in corr_results}

    ret_order, ret_map = [], {}
    for r in ret_all:
        if r["doc"] not in ret_map:
            ret_map[r["doc"]] = []
            ret_order.append(r["doc"])
        ret_map[r["doc"]].append(r)

    ret_results = []
    for dk in ret_order:
        lines = ret_map[dk]
        info = []
        for l in lines:
            m = ret_to_corr.get(l["idx"])
            info.append((l, [m[0]] if m else None))
        nm = sum(1 for _, m in info if m)
        res = DocResult(dk, lines[0]["num"], lines[0]["date"], status_of(nm, len(lines)), nm, len(lines), info)
        if res.status == "full":
            corr_docs = []
            for _, m in info:
                if m[0]["doc"] not in corr_docs:
                    corr_docs.append(m[0]["doc"])
            not_ready = [corr_by_doc[cd] for cd in corr_docs if corr_by_doc[cd].status != "full"]
            if not_ready:
                res.status = "partial"
                res.corr_not_ready = [c.num for c in not_ready]
        ret_results.append(res)
    return ret_results, corr_results


# ── Этап 2: планирование проведения цепочки корректировок ───────────────────────
# Эталон для BSL-процедуры ПровестиЦепочку (1c/СверкаВозвратов/.../ObjectModule.bsl).
from datetime import datetime, time, timedelta


def new_doc_date(current: datetime, posting_day: datetime) -> datetime:
    """Дата проведения — только день; время суток исходной даты сохраняется."""
    if current.date() == posting_day.date():
        return current
    return datetime.combine(posting_day.date(), time()) + (current - datetime.combine(current.date(), time()))


def plan_chain(items, selected, dry_run=False, allowed=None):
    """items — корректировки одного поступления по порядку даты/времени:
    {"num", "date": datetime, "posted": bool}; selected — {num: datetime дня проведения}.

    Возвращает записи [{"num", "ok": True|False|None, "refill": bool, "date": datetime|None, "msg": str}].
    allowed — {num: день проведения} непроведённых корректировок, сопоставленных с возвратами: их можно провести как
    «предыдущие». Первая непроведённая корректировка, которой нет ни в selected, ни в allowed (не сопоставилась),
    останавливает цепочку: всё до неё проводится, всё после — нет.
    Ошибка останавливает цепочку.
    """
    log = []
    prev_date = None
    has_prev = False
    simulated = False
    stopped = False
    skipped_num = None
    last_sel = -1
    for i, it in enumerate(items):
        if not it["posted"] and selected.get(it["num"]) is not None:
            last_sel = i
    for i, it in enumerate(items):
        if it["posted"]:
            prev_date, has_prev = it["date"], True
            continue
        day = selected.get(it["num"])
        added = False
        if day is None:
            if allowed and it["num"] in allowed and i < last_sel and not stopped:
                # не выбрана, но сопоставлена с возвратами и стоит раньше выбранной — проводим тоже
                day, added = allowed[it["num"]], True
            else:
                if skipped_num is None:
                    skipped_num = it["num"]
                continue
        if stopped:
            log.append({"num": it["num"], "ok": None, "refill": False, "date": None, "msg": "stopped"})
            continue
        if skipped_num is not None:
            log.append({"num": it["num"], "ok": False, "refill": False, "date": None, "msg": "blocked by " + skipped_num})
            stopped = True
            continue
        nd = new_doc_date(it["date"], day)
        if prev_date is not None and nd <= prev_date and nd.date() == prev_date.date():
            # тот же день, но время исходной даты нарушает порядок цепочки: ставим сразу после предыдущей
            nd = prev_date + timedelta(seconds=1)
            if nd.date() != prev_date.date():
                nd = prev_date  # день закончился — ниже сработает проверка порядка
        if prev_date is not None and nd <= prev_date:
            log.append({"num": it["num"], "ok": False, "refill": False, "date": nd, "msg": "date order"})
            stopped = True
            continue
        refill = has_prev and not simulated
        log.append({"num": it["num"], "ok": None if dry_run else True, "refill": refill, "date": nd,
                    "msg": "added" if added else ""})
        if dry_run:
            simulated = True
        prev_date, has_prev = nd, True
    return log
