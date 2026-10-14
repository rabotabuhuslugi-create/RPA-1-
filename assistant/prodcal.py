"""Производственный календарь РФ: рабочие / выходные / сокращённые дни и число рабочих дней.

Данные берутся с isdayoff.ru (официальные переносы), кэшируются в assistant_prodcal.json;
без интернета используется встроенный календарь 2026 года, для других лет — приближение
(Сб/Вс и федеральные праздники с переносом на понедельник).
Коды дня: "0" рабочий, "1" выходной/праздник, "2" сокращённый (предпраздничный).
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import time
import urllib.request
from pathlib import Path

CACHE = Path("assistant_prodcal.json")
RETRY_SECONDS = 7 * 86400
_FAILED: dict[str, float] = {}  # месяц -> когда не удалось (не долбим сеть чаще раза в 10 минут)

# Федеральные праздники РФ (месяц, день): Новый год 1–8 янв, 23 фев, 8 мар, 1 мая, 9 мая, 12 июн, 4 ноя
FIXED = [(1, d) for d in range(1, 9)] + [(2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4)]

# Официальный календарь 2026 (переносы: 3 янв→9 янв, 4 янв→31 дек, 8 мар→9 мар, 9 мая→11 мая)
HOLIDAYS_2026 = {dt.date(2026, 1, d) for d in range(1, 12)} | {
    dt.date(2026, 2, 23), dt.date(2026, 3, 9), dt.date(2026, 5, 1), dt.date(2026, 5, 11),
    dt.date(2026, 6, 12), dt.date(2026, 11, 4), dt.date(2026, 12, 31)}
SHORT_2026 = {dt.date(2026, 4, 30), dt.date(2026, 6, 11), dt.date(2026, 11, 3), dt.date(2026, 12, 30)}


def builtin(year: int, month: int) -> str:
    days = calendar.monthrange(year, month)[1]
    if year == 2026:
        off = HOLIDAYS_2026
        short = SHORT_2026
    else:
        off = set()
        for m, d in FIXED:
            day = dt.date(year, m, d)
            while day.weekday() >= 5 and (m, d) != (1, d):  # выходной праздник → следующий понедельник
                day += dt.timedelta(days=1)
            off.add(day)
        short = {d - dt.timedelta(days=1) for d in off
                 if (d - dt.timedelta(days=1)) not in off and (d - dt.timedelta(days=1)).weekday() < 5}
    out = []
    for n in range(1, days + 1):
        d = dt.date(year, month, n)
        out.append("1" if d.weekday() >= 5 or d in off else ("2" if d in short else "0"))
    return "".join(out)


def _load() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    except ValueError:
        return {}


def _fetch(year: int, month: int) -> str | None:
    url = f"https://isdayoff.ru/api/getdata?year={year}&month={month}&pre=1"
    try:
        text = urllib.request.urlopen(url, timeout=3).read().decode().strip()
    except Exception:
        return None
    n = calendar.monthrange(year, month)[1]
    if len(text) != n or any(c not in "0124" for c in text):
        return None
    return text.replace("4", "0")


def month_info(year: int, month: int) -> dict:
    key = f"{year}-{month:02d}"
    cache = _load()
    entry = cache.get(key)
    source = "cache"
    if not entry or time.time() - entry.get("checked", 0) > RETRY_SECONDS:
        fresh = None if time.time() - _FAILED.get(key, 0) < 600 else _fetch(year, month)
        if fresh is None:
            _FAILED[key] = time.time()
        if fresh:
            entry = {"days": fresh, "checked": time.time(), "online": True}
            cache[key] = entry
            CACHE.write_text(json.dumps(cache), encoding="utf-8")
        elif not entry:
            entry = {"days": builtin(year, month), "online": False}
    days = entry["days"]
    if not entry.get("online"):
        source = "builtin"
    work = days.count("0") + days.count("2")
    return {"year": year, "month": month, "days": days, "workdays": work,
            "dayoff": days.count("1"), "short": days.count("2"),
            "hours": days.count("0") * 8 + days.count("2") * 7, "source": source}
