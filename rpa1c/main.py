"""RPA: сканы документов -> OCR -> разбор -> документ в 1С:КА + прикрепленный скан."""
import argparse
import json
import logging
import shutil
import time
from pathlib import Path

from . import config as cfgmod
from .ocr import IMAGE_EXT, scan_to_text
from .onec import OneC
from .parser import parse

log = logging.getLogger("rpa1c")


def process(path: Path, cfg: dict, onec: OneC, dry_run: bool) -> None:
    text = scan_to_text(path, cfg["ocr"])
    dbg = Path(cfg["folders"].get("debug", "./debug"))
    dbg.mkdir(parents=True, exist_ok=True)
    (dbg / f"{path.name}.txt").write_text(text, encoding="utf-8")
    data = parse(text, cfg["onec"].get("own_inn"), filename=path.stem)
    log.info("%s: %s", path.name, data)
    if data.found() < cfg["rpa"]["min_confidence_fields"] or not (data.number and data.doc_date and data.inn):
        raise ValueError("Недостаточно реквизитов (нужны номер, дата, ИНН контрагента)")
    if dry_run:
        return
    doc = onec.create_document(data)
    onec.attach_scan(doc, path)
    if cfg["onec"].get("post_document"):
        onec.post_document(doc)
    log.info("Создан документ %s", doc.get("Number"))


def run_once(cfg: dict, dry_run: bool) -> int:
    onec = None if dry_run else OneC(cfg["onec"])
    inbox = Path(cfg["folders"]["inbox"])
    n = 0
    for f in sorted(inbox.iterdir()):
        if f.suffix.lower() not in IMAGE_EXT | {".pdf"}:
            continue
        n += 1
        try:
            process(f, cfg, onec, dry_run)
            if not dry_run:
                shutil.move(f, Path(cfg["folders"]["processed"]) / f.name)
        except Exception as e:  # noqa: BLE001
            log.error("%s: %s", f.name, e)
            if not dry_run:
                err = Path(cfg["folders"]["errors"])
                shutil.move(f, err / f.name)
                (err / f"{f.name}.error.json").write_text(
                    json.dumps({"error": str(e)}, ensure_ascii=False), encoding="utf-8"
                )
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--dry-run", action="store_true", help="только распознать, 1С не трогать")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = cfgmod.load(a.config)
    poll = cfg["rpa"]["poll_seconds"]
    log.info("Старт. Папка inbox: %s, интервал опроса: %s с (Ctrl+C - остановка)",
             Path(cfg["folders"]["inbox"]).resolve(), poll)
    try:
        while True:
            n = run_once(cfg, a.dry_run)
            log.info("Проход завершен, файлов обработано: %d", n)
            if not poll or a.dry_run:
                break
            log.info("Жду %s с до следующей проверки...", poll)
            time.sleep(poll)
    except KeyboardInterrupt:
        log.info("Остановлено пользователем")


if __name__ == "__main__":
    main()
