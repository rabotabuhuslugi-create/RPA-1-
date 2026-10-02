"""Показать заполненные реквизиты последнего документа из 1С - образец для extra_document_fields."""
import argparse
import json
from urllib.parse import quote

import requests

from . import config as cfgmod
from .onec import basic_auth

EMPTY_GUID = "00000000-0000-0000-0000-000000000000"


def meaningful(v) -> bool:
    return v not in (None, "", [], {}, EMPTY_GUID, False, 0, "0001-01-01T00:00:00")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--all", action="store_true", help="показать и пустые поля")
    a = ap.parse_args()
    o = cfgmod.load(a.config)["onec"]
    url = f"{o['base_url'].rstrip('/')}/{quote(o['document_entity'])}?$format=json&$top=1&$orderby=Date%20desc"
    r = requests.get(url, headers={"Authorization": basic_auth(o["user"], o["password"])},
                     verify=o.get("verify_tls", True), timeout=120)
    if not r.ok:
        raise SystemExit(f"1С {r.status_code}: {r.text[:500]}")
    rows = r.json().get("value", [])
    if not rows:
        raise SystemExit("В 1С нет ни одного документа этого вида. Создайте один вручную и повторите.")
    doc = {k: v for k, v in rows[0].items() if a.all or meaningful(v)}
    for k, v in list(doc.items()):
        if isinstance(v, list) and v:
            doc[k] = f"[табличная часть, строк: {len(v)}; первая: {json.dumps(v[0], ensure_ascii=False)[:300]}]"
    print(json.dumps(doc, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
