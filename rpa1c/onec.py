"""Клиент стандартного интерфейса OData 1С:Комплексная автоматизация."""
import base64
import logging
from pathlib import Path
from urllib.parse import quote

import requests

from .parser import DocData


def basic_auth(user: str, password: str) -> str:
    """Заголовок Basic в UTF-8 (requests по умолчанию кодирует в latin-1 и ломает кириллицу)."""
    return "Basic " + base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")


log = logging.getLogger("rpa1c")


class OneC:
    def __init__(self, cfg: dict):
        self.c = cfg
        self.base = cfg["base_url"].rstrip("/")
        self.s = requests.Session()
        self.s.headers["Authorization"] = basic_auth(cfg["user"], cfg["password"])
        self.s.verify = cfg.get("verify_tls", True)
        self.s.headers.update({"Accept": "application/json"})

    def _get(self, entity: str, flt: str, top: int = 1) -> list[dict]:
        url = f"{self.base}/{quote(entity)}?$format=json&$top={top}&$filter={quote(flt)}"
        r = self.s.get(url, timeout=60)
        if not r.ok:
            raise RuntimeError(f"1С {r.status_code} при запросе {entity}: {r.text[:500]}")
        return r.json().get("value", [])

    def _post(self, entity: str, body: dict) -> dict:
        r = self.s.post(f"{self.base}/{quote(entity)}?$format=json", json=body, timeout=120)
        if not r.ok:
            hint = ""
            if "Не удалось записать" in r.text:
                hint = ("\nПодсказка: 1С не записала объект, обычно не заполнены обязательные реквизиты. "
                        "Выполните `python -m rpa1c.sample`, чтобы увидеть, что заполнено в реальном документе, "
                        "и добавьте нужное в extra_document_fields (config.yaml).")
            raise RuntimeError(f"1С {r.status_code}: {r.text[:500]}{hint}")
        return r.json()

    def find_counterparty(self, inn: str, kpp: str | None) -> dict | None:
        flt = f"ИНН eq '{inn}'"
        rows = self._get(self.c["counterparty_entity"], flt, top=5)
        if kpp:
            rows = sorted(rows, key=lambda r: r.get("КПП") != kpp)
        return rows[0] if rows else None

    def find_contract(self, counterparty_key: str) -> str | None:
        """Первый действующий договор контрагента; поле владельца зависит от конфигурации."""
        fields = [self.c.get("contract_owner_field"), "Контрагент_Key", "Owner_Key"]
        for field in dict.fromkeys(f for f in fields if f):
            for extra in (" and DeletionMark eq false", ""):
                try:
                    rows = self._get(self.c["contract_entity"], f"{field} eq guid'{counterparty_key}'{extra}")
                except RuntimeError as e:
                    log.warning("Поиск договора по %s%s не удался: %s", field, extra, e)
                    continue
                return rows[0]["Ref_Key"] if rows else None
        return None

    def create_document(self, d: DocData) -> dict:
        cp = self.find_counterparty(d.inn, d.kpp)
        if not cp:
            raise LookupError(f"Контрагент с ИНН {d.inn} не найден в 1С")
        body = {
            "Date": f"{d.doc_date.isoformat()}T00:00:00",
            "Организация_Key": self.c["organization_key"],
            "Контрагент_Key": cp["Ref_Key"],
            "НомерВходящегоДокумента": d.number,
            "ДатаВходящегоДокумента": f"{d.doc_date.isoformat()}T00:00:00",
            "СуммаДокумента": float(d.total) if d.total is not None else 0,
            **self.c.get("extra_document_fields", {}),
        }
        if cp.get("Партнер_Key"):
            body["Партнер_Key"] = cp["Партнер_Key"]
        contract = self.find_contract(cp["Ref_Key"])
        if contract:
            body["Договор_Key"] = contract
        if self.c.get("warehouse_key"):
            body["Склад_Key"] = self.c["warehouse_key"]
        return self._post(self.c["document_entity"], body)

    def attach_scan(self, doc: dict, path: Path) -> dict:
        data = base64.b64encode(path.read_bytes()).decode()
        body = {
            "Description": path.stem,
            "Расширение": path.suffix.lstrip(".").lower(),
            "ВладелецФайла_Key": doc["Ref_Key"],
            "ВладелецФайла_Type": self.c["document_entity"].replace("Document_", "StandardODATA.Document_"),
            self.c["attachment_data_field"]: data,
        }
        return self._post(self.c["attachment_entity"], body)

    def post_document(self, doc: dict) -> None:
        url = f"{self.base}/{quote(self.c['document_entity'])}(guid'{doc['Ref_Key']}')/Post"
        r = self.s.post(url, timeout=120)
        r.raise_for_status()
