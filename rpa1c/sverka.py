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


def _find(avail, line, tol, max_combo):
    if not avail:
        return None
    for r in avail:
        if abs(r["qty"] - line["qty"]) <= tol:
            return [r]
    combo = subset_sum(avail, line["qty"], tol, max_combo)
    return combo if combo else None


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


def reconcile(ret_all, corr_all, tol=0.01, max_combo=6):
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
            "relevant": any(l["key"] in rb for l in lines), "resolved": False,
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

    # Раунд 1: закрываем документы корректировки целиком, от коротких к длинным
    for d in candidates:
        tentative_used, tentative = set(), []
        all_ok = True
        for line in d["lines"]:
            avail = [r for r in rb.get(line["key"], []) if r["idx"] not in used and r["idx"] not in tentative_used]
            found = _find(avail, line, tol, max_combo)
            if found:
                tentative_used.update(r["idx"] for r in found)
                tentative.append((line, found))
            else:
                all_ok = False
                break
        if all_ok and d["lines"]:
            for line, found in tentative:
                commit(line, found)
            d["resolved"] = True

    # Раунд 2: частичные совпадения для остальных
    for d in candidates:
        if d["resolved"]:
            continue
        for line in d["lines"]:
            if line["idx"] in line_match:
                continue
            avail = [r for r in rb.get(line["key"], []) if r["idx"] not in used]
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
