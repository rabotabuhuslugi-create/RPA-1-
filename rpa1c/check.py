"""Проверка подключения к 1С: какие нужные объекты опубликованы в OData."""
import argparse
import re
import sys

import requests

from . import config as cfgmod

BSL = """// Выполнить в 1С:Предприятие под администратором (Все функции -> Стандартные -> Выполнить код,
// либо внешней обработкой). Функция ЗАМЕНЯЕТ состав целиком, поэтому текущий состав сохраняем.
Состав = ПолучитьСоставСтандартногоИнтерфейсаOData();
{adds}
УстановитьСоставСтандартногоИнтерфейсаOData(Состав);"""

KIND = {"Catalog": "Справочники", "Document": "Документы"}


def published(base: str, auth, verify: bool) -> set[str]:
    r = requests.get(base.rstrip("/") + "/$metadata", auth=auth, verify=verify, timeout=120)
    r.raise_for_status()
    return set(re.findall(r'<EntitySet\s+Name="([^"]+)"', r.text))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--list", action="store_true", help="показать все опубликованные объекты")
    a = ap.parse_args()
    o = cfgmod.load(a.config)["onec"]
    names = published(o["base_url"], (o["user"], o["password"]), o.get("verify_tls", True))
    print(f"Опубликовано объектов: {len(names)}")
    if a.list:
        print("\n".join(sorted(names)))
    need = [o[k] for k in ("counterparty_entity", "contract_entity", "document_entity", "attachment_entity")]
    missing = []
    for n in need:
        if n in names:
            print(f"  OK       {n}")
        else:
            missing.append(n)
            word = n.split("_", 1)[-1][:8].lower()
            sim = [x for x in sorted(names) if word in x.lower()][:5]
            print(f"  НЕТ      {n}" + (f"   (похожие: {', '.join(sim)})" if sim else ""))
    if not missing:
        print("Все нужные объекты опубликованы.")
        return 0
    adds = []
    for n in missing:
        kind, name = n.split("_", 1)
        if kind in KIND:
            adds.append(f"Состав.Добавить(Метаданные.{KIND[kind]}.{name});")
    print("\nДобавьте недостающие объекты в состав OData. Код для 1С:\n")
    print(BSL.format(adds="\n".join(adds)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
