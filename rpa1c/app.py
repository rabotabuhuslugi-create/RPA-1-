"""Программа для пользователя: один запуск = робот + панель управления в браузере.

Двойной щелчок по RPA1C.exe (или start.bat). Все настройки задаются в браузере, во вкладке «Настройки».
"""
import logging
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import config as cfgmod
from .dashboard import serve
from .main import run_once
from .state import State

log = logging.getLogger("rpa1c")


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


def robot_loop(cfg: dict, st: State, stop: threading.Event) -> None:
    seen: set = set()  # в тестовом режиме файлы остаются в inbox - не обрабатываем повторно
    st.set_status(state="idle", started_at=time.time(), current=None, stage=None, next_run=None)
    while not stop.is_set():
        poll = max(5, int(cfg["rpa"].get("poll_seconds") or 30))
        try:
            if st.paused() or (not cfgmod.is_configured(cfg) and not cfg["rpa"].get("dry_run")):
                st.set_status(state="paused" if st.paused() else "idle", dry_run=False,
                              stage=None if st.paused() else "Заполните настройки 1С", next_run=None)
            else:
                dry = bool(cfg["rpa"].get("dry_run"))
                st.set_status(state="working", dry_run=dry, stage=None, next_run=None)
                run_once(cfg, dry, st, seen if dry else None)
                st.set_status(state="idle", stage=None, next_run=time.time() + poll)
        except Exception as e:  # noqa: BLE001  робот не должен падать
            log.error("Ошибка прохода: %s", e)
        for _ in range(poll if not st.paused() else 1):
            if stop.is_set():
                return
            time.sleep(1)
            st.set_status()


def main() -> None:
    os.chdir(base_dir())
    cfg = cfgmod.load("config.yaml")
    first_run = not Path("config.yaml").exists()
    if first_run:
        cfgmod.save(cfg)
    st = State(cfg["folders"]["state"])
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(st.log_file, encoding="utf-8")],
    )
    d = cfg["dashboard"]
    url = f"http://{d['host']}:{d['port']}"
    try:
        serve(cfg, st, block=False)
    except OSError:
        webbrowser.open(url)  # уже запущена: просто открываем панель
        print("Программа уже запущена, открываю панель.")
        return
    stop = threading.Event()
    threading.Thread(target=robot_loop, args=(cfg, st, stop), daemon=True).start()
    print(f"RPA 1С запущена. Панель: {url}\nНе закрывайте это окно, пока нужна работа робота.")
    webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
