"""RPA: сканы документов -> OCR -> разбор -> документ в 1С:КА + прикрепленный скан."""
import argparse
import json
import logging
import shutil
import time
import webbrowser
from pathlib import Path

from . import config as cfgmod
from .ocr import IMAGE_EXT, scan_to_text
from .onec import OneC
from .parser import parse
from .state import State

log = logging.getLogger("rpa1c")


def process(path: Path, cfg: dict, onec: OneC | None, dry_run: bool, st: State, rec: dict) -> None:
    st.set_status(current=path.name, stage="Распознавание (OCR)")
    log.info("Начало: %s", path.name)
    text = scan_to_text(path, cfg["ocr"])
    dbg = Path(cfg["folders"].get("debug", "./debug"))
    dbg.mkdir(parents=True, exist_ok=True)
    (dbg / f"{path.name}.txt").write_text(text, encoding="utf-8")

    st.set_status(stage="Разбор реквизитов")
    data = parse(text, cfg["onec"].get("own_inn"), filename=path.stem)
    rec.update(
        number=data.number, date=data.doc_date.isoformat() if data.doc_date else None,
        inn=data.inn, total=float(data.total) if data.total is not None else None,
        vat=float(data.vat) if data.vat is not None else None,
    )
    log.info("%s: %s", path.name, data)
    if data.found() < cfg["rpa"]["min_confidence_fields"] or not (data.number and data.doc_date and data.inn):
        raise ValueError("Недостаточно реквизитов (нужны номер, дата, ИНН контрагента)")
    if dry_run:
        rec["status"] = "recognized"
        return
    st.set_status(stage="Создание документа в 1С")
    doc = onec.create_document(data)
    rec["doc_number"] = doc.get("Number")
    st.set_status(stage="Прикрепление скана")
    onec.attach_scan(doc, path)
    if cfg["onec"].get("post_document"):
        st.set_status(stage="Проведение документа")
        onec.post_document(doc)
    rec["status"] = "loaded"
    log.info("Создан документ %s", doc.get("Number"))


def run_once(cfg: dict, dry_run: bool, st: State) -> int:
    onec = None if dry_run else OneC(cfg["onec"])
    inbox = Path(cfg["folders"]["inbox"])
    n = 0
    for f in sorted(inbox.iterdir()):
        if f.suffix.lower() not in IMAGE_EXT | {".pdf"}:
            continue
        if st.paused():
            break
        n += 1
        rec = {"file": f.name, "status": "error"}
        t0 = time.time()
        try:
            process(f, cfg, onec, dry_run, st, rec)
            if not dry_run:
                shutil.move(f, Path(cfg["folders"]["processed"]) / f.name)
        except Exception as e:  # noqa: BLE001
            log.error("%s: %s", f.name, e)
            rec.update(status="error", error=str(e)[:500])
            if not dry_run:
                err = Path(cfg["folders"]["errors"])
                shutil.move(f, err / f.name)
                (err / f"{f.name}.error.json").write_text(
                    json.dumps({"error": str(e)}, ensure_ascii=False), encoding="utf-8"
                )
        rec["seconds"] = round(time.time() - t0, 1)
        st.add_history(rec)
        st.set_status(current=None, stage=None)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--dry-run", action="store_true", help="только распознать, 1С не трогать")
    ap.add_argument("--dashboard", action="store_true", help="запустить веб-панель вместе с роботом")
    ap.add_argument("--no-browser", action="store_true", help="не открывать браузер автоматически")
    a = ap.parse_args()
    cfg = cfgmod.load(a.config)
    st = State(cfg["folders"].get("state", "./state"))
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(st.log_file, encoding="utf-8")],
    )
    poll = cfg["rpa"]["poll_seconds"]
    st.set_status(state="idle", started_at=time.time(), dry_run=a.dry_run, current=None, stage=None, next_run=None)
    if a.dashboard:
        from .dashboard import serve

        d = cfg.get("dashboard", {})
        url = f"http://{d.get('host', '127.0.0.1')}:{d.get('port', 8765)}"
        serve(cfg, st, block=False)
        log.info("Панель управления: %s", url)
        if not a.no_browser:
            webbrowser.open(url)
    log.info("Старт. Папка inbox: %s, интервал опроса: %s с (Ctrl+C - остановка)",
             Path(cfg["folders"]["inbox"]).resolve(), poll)
    try:
        while True:
            if st.paused() and poll:
                st.set_status(state="paused", next_run=None)
                time.sleep(1)
                continue
            st.set_status(state="working", next_run=None)
            n = run_once(cfg, a.dry_run, st)
            log.info("Проход завершен, файлов обработано: %d", n)
            if not poll or a.dry_run:
                break
            until = time.time() + poll
            st.set_status(state="idle", next_run=until)
            while time.time() < until and not st.paused():
                time.sleep(1)
                st.set_status()  # heartbeat
    except KeyboardInterrupt:
        log.info("Остановлено пользователем")
    finally:
        st.set_status(state="stopped", current=None, stage=None, next_run=None)


if __name__ == "__main__":
    main()
