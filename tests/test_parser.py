from datetime import date
from decimal import Decimal

from rpa1c.parser import parse

TEXT = """Счет-фактура № 125/А от 14 марта 2025 г.
Продавец: ООО "Ромашка"
ИНН/КПП продавца: ИНН 7701234567 КПП 770101001
Покупатель: ООО "Наша"  ИНН 7700000000
Всего к оплате 123 456,78
В том числе НДС 20 576,13
"""


def test_parse():
    d = parse(TEXT, own_inn="7700000000")
    assert d.number == "125/А"
    assert d.doc_date == date(2025, 3, 14)
    assert d.inn == "7701234567"
    assert d.kpp == "770101001"
    assert d.total == Decimal("123456.78")
    assert d.vat == Decimal("20576.13")


UPD = """Универсальный передаточный документ
Счет-фактура № ТК0000000309 от 31 августа 2026 г. (1)
Продавец: ИП Иванов  ИНН 263203039147
Покупатель: ООО "Наша" ИНН/КПП 2310050943/231001001
Всего к оплате (9)   100 000,00   X   20 000,00   120 000,00
"""


def test_upd_table_and_prefixed_number():
    d = parse(UPD, own_inn="2310050943")
    assert d.number == "ТК0000000309"
    assert d.inn == "263203039147"
    assert d.total == Decimal("120000.00")
    assert d.vat == Decimal("20000.00")


def test_filename_fallback_and_two_digit_year():
    d = parse("мусор без реквизитов", filename="УПД №950 от 18.09.26")
    assert d.number == "950"
    assert d.doc_date == date(2026, 9, 18)


def test_regulation_date_ignored():
    text = ("Приложение N 1 к постановлению Правительства РФ от 26 декабря 2011 г. N 1137\n"
            "Счет-фактура № ТК0000000309 (1)\nПродавец ИНН 263203039147\n")
    d = parse(text, filename="УПД №ТК0000000309 от 31.08.26")
    assert d.doc_date == date(2026, 8, 31)
