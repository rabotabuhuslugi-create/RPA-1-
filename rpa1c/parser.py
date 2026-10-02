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
    m = re.search(r"\b(\d{2})[./](\d{2})[./](\d{4}|\d{2})\b", text)
    if m:
        y = int(m[3])
        y = y + 2000 if y < 100 else y
        try:
            return date(y, int(m[2]), int(m[1]))
        except ValueError:
            return None
    return None


MONEY = r"\d{1,3}(?:[ \u00a0]\d{3})+[.,]\d{2}|\d+[.,]\d{2}"


def _amounts(text: str) -> list[Decimal]:
    out = []
    for m in re.finditer(MONEY, text):
        v = _money(m[0])
        if v is not None:
            out.append(v)
    return out


def _number_from_name(name: str | None) -> str | None:
    if not name:
        return None
    m = re.search(r"(?:№|N)\s*([\w\-/]+)", name)
    return m[1] if m else None


def _date_from_name(name: str | None) -> date | None:
    return _date(name) if name else None


def _valid(d: date | None) -> date | None:
    """Дата документа не может быть древней или из далекого будущего."""
    if d and 2015 <= d.year <= date.today().year + 1:
        return d
    return None


def _clean_dates(text: str) -> str:
    """Убираем строки-ссылки на нормативные акты (в шапке УПД: 'от 26 декабря 2011 г. N 1137')."""
    return "\n".join(
        ln for ln in text.splitlines()
        if not re.search(r"постановлен|правительств|приложение\s*N?\s*\d", ln, re.I)
    )


def parse(text: str, own_inn: str | None = None, filename: str | None = None) -> DocData:
    d = DocData()
    # номер: после слова-заголовка и знака №; допускаем буквенный префикс (ТК000123)
    m = re.search(
        r"(?:счет[- ]?фактура|счет|накладная|упд|универсальный\s+передаточный\s+документ|акт)"
        r"[^\n№]{0,60}?(?:№|N[o°]?\.?)\s*([A-Za-zА-Яа-я]{0,5}[\d][\w\-/]*)"
        r"([^\n]{0,40})",
        text, re.I,
    )
    if m:
        d.number = m[1].strip()
        d.doc_date = _valid(_date(m[2]))
    # запасной вариант: имя файла вида "УПД №950 от 18.09.26.pdf"
    if d.number is None or not re.search(r"\d", d.number):
        d.number = _number_from_name(filename) or d.number
    if d.doc_date is None:
        d.doc_date = _valid(_date_from_name(filename))
    if d.doc_date is None:
        d.doc_date = _valid(_date(_clean_dates(text)))

    inns = re.findall(r"ИНН[^\d\n]{0,25}(\d{10}|\d{12})\b", text)
    d.org_inns = list(dict.fromkeys(inns))
    for i in d.org_inns:
        if i != own_inn:
            d.inn = i
            break
    m = re.search(r"КПП[^\d\n]{0,25}(\d{9})\b", text)
    d.kpp = m[1] if m else None

    d.total, d.vat = _totals(text)
    if d.vat is None:
        m = re.search(r"НДС[^\d\n]{0,30}(" + MONEY + ")", text, re.I)
        if m:
            d.vat = _money(m[1])
    return d


def _totals(text: str) -> tuple[Decimal | None, Decimal | None]:
    lines = text.splitlines()
    for key in (r"всего\s+к\s+оплате", r"всего\s+по\s+счету", r"итого\s+к\s+оплате",
                r"к\s+оплате", r"итого", r"всего"):
        for idx, ln in enumerate(lines):
            if re.search(key, ln, re.I):
                # строка итогов УПД: [сумма без НДС] [акциз] [НДС] [сумма с НДС];
                # иногда числа переносятся на следующие строки
                nums = _amounts(ln)
                span = 1
                while not nums and span < 3 and idx + span < len(lines):
                    nums = _amounts(lines[idx + span])
                    span += 1
                if not nums:
                    continue
                total = nums[-1]
                vat = nums[-2] if len(nums) >= 3 else None
                m = re.search(r"НДС[^\d\n]*(" + MONEY + ")", " ".join(lines[idx:idx + span + 1]), re.I)
                if m and len(nums) > 1:
                    vat = _money(m[1])
                if re.search(r"без\s+НДС", " ".join(lines[idx:idx + span + 1]), re.I):
                    vat = Decimal("0")
                return total, vat
    nums = _amounts(text)
    return (max(nums) if nums else None), None
