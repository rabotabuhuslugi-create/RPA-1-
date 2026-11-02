import copy
import os
import re
from pathlib import Path

import yaml

DEFAULTS = {
    "folders": {"inbox": "./inbox", "processed": "./processed", "errors": "./errors",
                "debug": "./debug", "state": "./state"},
    "ocr": {
        "engine": "xiaomi", "fallback_tesseract": True,
        "xiaomi": {"url": "http://127.0.0.1:11434", "model": "richardyoung/xiaomi-ocr-0",
                   "max_side": 2048, "timeout": 300},
        "lang": "rus+eng", "tesseract_cmd": None, "poppler_path": None, "dpi": 300,
    },
    "onec": {
        "base_url": "", "user": "", "password": "", "password_env": "ONEC_PASSWORD",
        "verify_tls": True, "own_inn": "", "organization_key": "", "warehouse_key": None,
        "department_key": None, "currency_key": None,
        "document_entity": "Document_ПриобретениеТоваровУслуг",
        "counterparty_entity": "Catalog_Контрагенты",
        "contract_entity": "Catalog_ДоговорыКонтрагентов",
        "contract_owner_field": "Контрагент_Key",
        "attachment_entity": "Catalog_ПриобретениеТоваровУслугПрисоединенныеФайлы",
        "attachment_data_field": "ФайлХранилище_Base64",
        "post_document": False, "extra_document_fields": {},
    },
    "rpa": {"poll_seconds": 30, "min_confidence_fields": 3, "dry_run": False},
    "dashboard": {"host": "127.0.0.1", "port": 8765},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_file(path: str) -> dict:
    p = Path(path)
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def load(path: str = "config.yaml") -> dict:
    """Читает config.yaml поверх значений по умолчанию (файла может не быть)."""
    cfg = _merge(DEFAULTS, _read_file(path))
    env = cfg["onec"].get("password_env") or ""
    if env and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env):
        raise SystemExit(
            "config.yaml: onec.password_env должен содержать ИМЯ переменной окружения "
            "(например ONEC_PASSWORD), а не сам пароль. Пароль можно вписать в onec.password."
        )
    if env and os.environ.get(env):
        cfg["onec"]["password"] = os.environ[env]
    for k in cfg["folders"].values():
        Path(k).mkdir(parents=True, exist_ok=True)
    cfg["_path"] = path
    return cfg


def save(cfg: dict, path: str | None = None) -> None:
    path = path or cfg.get("_path", "config.yaml")
    data = {k: v for k, v in cfg.items() if not k.startswith("_")}
    Path(path).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def replace_in_place(cfg: dict, new: dict) -> None:
    """Подменяет содержимое cfg, не меняя сам объект (его держат робот и панель)."""
    cfg.clear()
    cfg.update(new)


def is_configured(cfg: dict) -> bool:
    o = cfg["onec"]
    return bool(o.get("base_url") and o.get("user") and o.get("password"))
