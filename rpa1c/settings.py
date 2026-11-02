"""Настройки для панели: чтение/сохранение, проверка 1С и модели распознавания, загрузка модели."""
import threading

import requests

from . import config as cfgmod

# поле формы -> путь в конфиге
FIELDS = {
    "base_url": ("onec", "base_url"), "user": ("onec", "user"), "password": ("onec", "password"),
    "own_inn": ("onec", "own_inn"), "organization_key": ("onec", "organization_key"),
    "warehouse_key": ("onec", "warehouse_key"), "department_key": ("onec", "department_key"),
    "post_document": ("onec", "post_document"), "dry_run": ("rpa", "dry_run"),
    "poll_seconds": ("rpa", "poll_seconds"), "model": ("ocr", "xiaomi", "model"),
    "engine": ("ocr", "engine"),
}


def _get(cfg, path):
    for p in path:
        cfg = cfg[p]
    return cfg


def _set(cfg, path, v):
    for p in path[:-1]:
        cfg = cfg[p]
    cfg[path[-1]] = v


def read(cfg: dict) -> dict:
    out = {k: _get(cfg, p) for k, p in FIELDS.items() if k != "password"}
    out["has_password"] = bool(cfg["onec"].get("password"))
    out["configured"] = cfgmod.is_configured(cfg)
    return out


def update(cfg: dict, form: dict) -> None:
    for k, v in form.items():
        if k not in FIELDS:
            continue
        if k == "password" and not v:
            continue  # пустое поле = оставить прежний пароль
        if k in ("post_document", "dry_run"):
            v = bool(v)
        elif k == "poll_seconds":
            v = max(0, int(v))
        elif isinstance(v, str):
            v = v.strip() or (None if k.endswith("_key") and k != "organization_key" else "")
        _set(cfg, FIELDS[k], v)
    cfgmod.save(cfg)


def test_onec(cfg: dict) -> dict:
    from .check import published

    o = cfg["onec"]
    if not cfgmod.is_configured(cfg):
        return {"ok": False, "message": "Заполните адрес, логин и пароль 1С"}
    try:
        names = published(o["base_url"], o["user"], o["password"], o.get("verify_tls", True))
    except PermissionError:
        return {"ok": False, "message": "1С не приняла логин или пароль"}
    except LookupError:
        return {"ok": False, "message": "Неверный адрес: по нему нет OData 1С"}
    except requests.RequestException as e:
        return {"ok": False, "message": f"Нет связи с 1С: {e}"}
    need = [o[k] for k in ("counterparty_entity", "contract_entity", "document_entity", "attachment_entity")]
    missing = [n for n in need if n not in names]
    if missing:
        return {"ok": False, "message": "Подключение есть, но в 1С не опубликованы объекты: "
                + ", ".join(missing) + ". Передайте это администратору 1С."}
    return {"ok": True, "message": "Связь с 1С работает, все нужные объекты опубликованы"}


def _ollama(cfg):
    x = cfg["ocr"]["xiaomi"]
    return x["url"].rstrip("/"), x["model"]


def models(cfg: dict) -> list[str]:
    url, _ = _ollama(cfg)
    r = requests.get(url + "/api/tags", timeout=5)
    r.raise_for_status()
    return [m["name"] for m in r.json().get("models", [])]


def test_ocr(cfg: dict) -> dict:
    url, model = _ollama(cfg)
    try:
        have = models(cfg)
    except requests.RequestException:
        return {"ok": False, "need": "ollama",
                "message": "Программа Ollama не запущена или не установлена (ollama.com/download)"}
    if not any(n == model or n == model + ":latest" for n in have):
        return {"ok": False, "need": "model", "message": f"Модель {model} ещё не скачана"}
    return {"ok": True, "message": "Модель распознавания готова"}


PULL = {"running": False, "status": "", "percent": 0, "error": None}


def start_pull(cfg: dict) -> None:
    if PULL["running"]:
        return
    url, model = _ollama(cfg)
    PULL.update(running=True, status="Подключение…", percent=0, error=None)

    def work():
        try:
            with requests.post(url + "/api/pull", json={"model": model, "stream": True},
                               stream=True, timeout=(10, 600)) as r:
                r.raise_for_status()
                import json

                for line in r.iter_lines():
                    if not line:
                        continue
                    d = json.loads(line)
                    if d.get("error"):
                        raise RuntimeError(d["error"])
                    PULL["status"] = d.get("status", "")
                    if d.get("total"):
                        PULL["percent"] = int(100 * d.get("completed", 0) / d["total"])
            PULL.update(status="Готово", percent=100)
        except Exception as e:  # noqa: BLE001
            PULL["error"] = str(e)[:300]
        finally:
            PULL["running"] = False

    threading.Thread(target=work, daemon=True).start()
