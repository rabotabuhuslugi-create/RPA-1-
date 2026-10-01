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
