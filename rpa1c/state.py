"""Общее состояние робота (файлы в папке state/): статус, история, пауза.

Робот и панель управления могут работать в разных процессах, поэтому обмен идёт через файлы.
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path


class State:
    def __init__(self, folder: str | Path):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.status_file = self.dir / "status.json"
        self.history_file = self.dir / "history.jsonl"
        self.pause_file = self.dir / "paused.flag"
        self.log_file = self.dir / "robot.log"
        self._status: dict = {}

    # --- статус ---
    def set_status(self, **kw) -> None:
        self._status.update(kw)
        self._status["heartbeat"] = time.time()
        self._status["pid"] = os.getpid()
        tmp = self.status_file.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self._status, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.status_file)
        except OSError:
            pass  # файл занят читателем (Windows) - обновим при следующем вызове

    def get_status(self) -> dict:
        try:
            return json.loads(self.status_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    # --- история ---
    def add_history(self, rec: dict) -> None:
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), **rec}
        with self.history_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def history(self, limit: int | None = None) -> list[dict]:
        try:
            lines = self.history_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
        return out[-limit:] if limit else out

    # --- пауза ---
    def paused(self) -> bool:
        return self.pause_file.exists()

    def set_paused(self, value: bool) -> None:
        if value:
            self.pause_file.write_text("1")
        elif self.pause_file.exists():
            self.pause_file.unlink()

    def log_tail(self, n: int = 150) -> list[str]:
        try:
            return self.log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
        except OSError:
            return []
