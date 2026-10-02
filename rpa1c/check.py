"""Проверка подключения к 1С: какие нужные объекты опубликованы в OData."""
import argparse
import re
import sys

import requests

from . import config as cfgmod
from .onec import basic_auth

BSL = """// Выполнить в 1С:Предприятие под администратором (Все функции -> Стандартные -> Выполнить код,
// либо внешней обработкой). Функция ЗАМЕНЯЕТ состав целиком, поэтому текущий состав сохраняем.
Состав = ПолучитьСоставСтандартногоИнтерфейсаOData();
{adds}
УстановитьСоставСтандартногоИнтерфейсаOData(Состав);"""

KIND = {"Catalog": "Справочники", "Document": "Документы"}


def published(base: str, user: str, password: str, verify: bool) -> set[str]:
    r = requests.get(base.rstrip("/") + "/$metadata", headers={"Authorization": basic_auth(user, password)},
                     verify=verify, timeout=120)
    if r.status_code == 401:
        raise PermissionError("401: 1С не приняла логин/пароль")
    if r.status_code == 404:
        raise LookupError("404: неверный адрес base_url или OData не опубликован")
    r.raise_for_status()
    return set(re.findall(r'<EntitySet\s+Name="([^"]+)"', r.text))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--list", action="store_true", help="показать все опубликованные объекты")
    a = ap.parse_args()
    o = cfgmod.load(a.config)["onec"]
    print(f"Адрес:  {o['base_url']}")
    print(f"Логин:  {o['user']!r}")
    print(f"Пароль: {'задан, символов: ' + str(len(o['password'])) if o['password'] else 'НЕ ЗАДАН (переменная ' + o.get('password_env', '?') + ' пуста)'}")
    try:
        names = published(o["base_url"], o["user"], o["password"], o.get("verify_tls", True))
    except (PermissionError, LookupError, requests.RequestException) as e:
        print(f"\nОШИБКА: {e}")
        if isinstance(e, PermissionError):
            print("Проверьте: 1) логин в config.yaml (точно как в 1С, с учетом регистра и раскладки);"
                  "\n2) пароль: $env:ONEC_PASSWORD = 'пароль' в ЭТОМ же окне PowerShell;"
                  "\n3) у пользователя в 1С включена аутентификация 1С:Предприятия и есть доступ к OData.")
        return 2
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
