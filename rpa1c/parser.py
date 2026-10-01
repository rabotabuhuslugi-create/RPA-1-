"""Извлечение реквизитов из распознанного текста счета/накладной/УПД."""
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}


@dataclass
class DocData:
    number: str | None = None
    doc_date: date | None = None
    inn: str | None = None
    kpp: str | None = None
    total: Decimal | None = None
    vat: Decimal | None = None
    org_inns: list[str] = field(default_factory=list)

    def found(self) -> int:
        return sum(x is not None for x in (self.number, self.doc_date, self.inn, self.total))


def _money(s: str) -> Decimal | None:
    s = s.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _date(text: str) -> date | None:
    m = re.search(r"(\d{1,2})\s+(%s)\s+(\d{4})" % "|".join(MONTHS), text, re.I)
    if m:
        return date(int(m[3]), MONTHS[m[2].lower()], int(m[1]))
    m = re.search(r"\b(\d{2})[./](\d{2})[./](\d{4})\b", text)
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            return None
    return None


def parse(text: str, own_inn: str | None = None) -> DocData:
    d = DocData()
    m = re.search(
        r"(?:счет[- ]фактура|счет|накладная|упд|акт)[^\n№N]{0,40}(?:№|N|No)\s*([\w\-/]+)"
        r"(?:\s+от\s+)?([^\n]{0,30})",
        text, re.I,
    )
    if m:
        d.number = m[1].strip()
        d.doc_date = _date(m[2])
    if d.doc_date is None:
        d.doc_date = _date(text)

    inns = re.findall(r"ИНН[:\s/А-Яа-я]*?(\d{10}|\d{12})\b", text)
    d.org_inns = list(dict.fromkeys(inns))
    # контрагент = первый ИНН, не равный ИНН нашей организации
    for i in d.org_inns:
        if i != own_inn:
            d.inn = i
            break
    m = re.search(r"КПП[:\s/А-Яа-я]*?(\d{9})\b", text)
    d.kpp = m[1] if m else None

    m = re.search(r"всего\s+к\s+оплате[^\d\n]*([\d\s\u00a0]+[.,]\d{2})", text, re.I) or \
        re.search(r"итого[^\d\n]*([\d\s\u00a0]+[.,]\d{2})", text, re.I)
    if m:
        d.total = _money(m[1])
    m = re.search(r"(?:в\s+т\.?\s*ч\.?\s*)?НДС[^\d\n]*([\d\s\u00a0]+[.,]\d{2})", text, re.I)
    if m:
        d.vat = _money(m[1])
    return d
