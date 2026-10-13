"""Локальный сервер помощника: Google API + уведомления + современный веб-интерфейс."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from . import imap_mail
from .google_api import Google
from .notifier import notify
from .watcher import due_reminders, new_mail, reminder_text

VERSION = "4"
CONFIG_PATH = Path("assistant_config.yaml")
TOKEN_PATH = Path(".assistant_token")
EVENTS_PATH = Path("assistant_events.json")
TASKS_PATH = Path("assistant_tasks.json")
MAIL_PATH = Path("assistant_mail.json")
UNSAFE_EXT = {".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".lnk", ".scr", ".com", ".jar", ".reg", ".hta"}
WEB = Path(__file__).parent / "web"
DEFAULTS = {
    "credentials_file": "credentials.json", "token_file": "token.json",
    "calendar_poll_seconds": 60, "mail_poll_seconds": 120, "default_lead_minutes": 10,
    "events_days_ahead": 62, "notify_calendar": True, "notify_mail": True, "drive_folders": [], "local_folders": [],
}
EDITABLE = ("calendar_poll_seconds", "mail_poll_seconds", "default_lead_minutes", "notify_calendar", "notify_mail")


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cfg.update(yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {})
    return cfg


def get_token() -> str:
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    t = secrets.token_urlsafe(24)
    TOKEN_PATH.write_text(t)
    return t


def load_local() -> list[dict]:
    if EVENTS_PATH.exists():
        try:
            return json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
        except ValueError:
            return []
    return []


def local_to_event(e: dict) -> dict:
    """Запись своего календаря -> тот же вид, что у событий Google."""
    if e.get("all_day"):
        start = dt.datetime.combine(dt.date.fromisoformat(e["date"]), dt.time.min).astimezone()
    else:
        start = dt.datetime.fromisoformat(f"{e['date']}T{e.get('time') or '09:00'}").astimezone()
    lead = e.get("lead")
    return {"id": e["id"], "summary": e["title"], "start": start, "all_day": bool(e.get("all_day")),
            "leads": [int(lead)] if lead not in (None, "") else [], "use_default": lead in (None, ""),
            "location": e.get("location", ""), "link": "", "local": True}


class Core:
    def __init__(self):
        self.cfg = load_config()
        self.token = get_token()
        self.g = Google(self.cfg["credentials_file"], self.cfg["token_file"])
        self.google_events, self.events, self.mail, self.alerts = [], [], [], []
        self.local = load_local()
        self.seen_rem, self.seen_mail, self.mail_first = set(), set(), True
        self.error, self.connecting, self.mail_error = "", False, ""
        self.wake = threading.Event()
        self.mail_wake = threading.Event()
        self.lock = threading.Lock()
        for fn in (self._calendar_loop, self._mail_loop):
            threading.Thread(target=fn, daemon=True).start()

    def alert(self, title, text):
        with self.lock:
            self.alerts.append({"id": len(self.alerts) + 1, "title": title, "text": text})
            self.alerts = self.alerts[-50:]
        if not notify(title, text):
            pass  # страница всё равно покажет карточку-уведомление

    def rebuild(self):
        mine = [local_to_event(e) for e in self.local]
        self.events = sorted(self.google_events + mine, key=lambda e: e["start"])

    def _calendar_loop(self):
        while True:
            if self.g.connected():
                try:
                    self.google_events = self.g.events(days=int(self.cfg["events_days_ahead"]))
                    self.error = ""
                except Exception as ex:
                    self.error = str(ex)
            self.rebuild()
            if self.cfg["notify_calendar"]:
                for e, left in due_reminders(self.events, dt.datetime.now(dt.timezone.utc),
                                             int(self.cfg["default_lead_minutes"]), self.seen_rem):
                    self.alert("Календарь", reminder_text(e, left))
            self.wake.wait(min(int(self.cfg["calendar_poll_seconds"]), 30) if not self.g.connected()
                           else int(self.cfg["calendar_poll_seconds"]))
            self.wake.clear()

    # ---------- свои задачи ----------
    def _read(self, path):
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        except ValueError:
            return []

    def tasks(self):
        if self.g.connected():
            return self.g.tasks()
        return [t for t in self._read(TASKS_PATH) if not t["done"]]

    def task_add(self, title, due):
        if self.g.connected():
            return self.g.add_task(title, dt.date.fromisoformat(due) if due else None)
        if due:
            dt.date.fromisoformat(due)
        items = self._read(TASKS_PATH)
        items.insert(0, {"id": "T" + secrets.token_hex(5), "title": title, "due": due or "", "done": False})
        TASKS_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    def task_change(self, tid, delete=False):
        if self.g.connected() and not tid.startswith("T"):
            return self.g.delete_task(tid) if delete else self.g.complete_task(tid)
        items = [t for t in self._read(TASKS_PATH) if not (delete and t["id"] == tid)]
        for t in items:
            if t["id"] == tid and not delete:
                t["done"] = True
        TASKS_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------- файлы компьютера ----------
    def roots(self) -> list[Path]:
        paths = self.cfg.get("local_folders") or [str(Path.home() / n) for n in ("Documents", "Desktop", "Downloads", "Документы", "Рабочий стол")]
        return [Path(p).expanduser().resolve() for p in paths if Path(p).expanduser().is_dir()]

    def safe(self, raw: str) -> Path:
        p = Path(raw).expanduser().resolve()
        for r in self.roots():
            if p == r or r in p.parents:
                return p
        raise PermissionError("Эта папка не добавлена в настройках")

    def files(self, raw: str):
        if not raw:
            return [{"name": r.name or str(r), "path": str(r), "folder": True, "modified": ""} for r in self.roots()]
        p = self.safe(raw)
        out = []
        for c in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if c.name.startswith("."):
                continue
            try:
                out.append({"name": c.name, "path": str(c), "folder": c.is_dir(),
                            "modified": dt.datetime.fromtimestamp(c.stat().st_mtime).strftime("%d.%m.%Y")})
            except OSError:
                pass
        return out[:300]

    def open_path(self, raw: str):
        p = self.safe(raw)
        if p.suffix.lower() in UNSAFE_EXT:
            raise PermissionError("Программы и скрипты отсюда не запускаются")
        if sys.platform == "win32":
            os.startfile(str(p))  # noqa: S606
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(p)])

    # ---------- почта IMAP ----------
    def mail_account(self):
        data = self._read_obj(MAIL_PATH)
        return data if data.get("email") and data.get("password") else {}

    @staticmethod
    def _read_obj(path):
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except ValueError:
            return {}

    def mail_save(self, address, password):
        address = address.strip()
        if "@" not in address or not password:
            raise ValueError("Введите почту и пароль приложения")
        try:
            imap_mail.fetch_unread(address, password, limit=1)  # проверка входа
        except Exception as ex:
            text = str(ex)
            if "AUTHENTICATIONFAILED" in text or "LOGIN failed" in text or "Invalid credentials" in text:
                raise ValueError("Почта не приняла пароль. Нужен «пароль для внешних приложений» "
                                 "(не обычный пароль) — см. подсказку под кнопкой.") from None
            raise ValueError(f"Не удалось подключиться: {text}") from None
        MAIL_PATH.write_text(json.dumps({"email": address, "password": password}), encoding="utf-8")
        try:
            MAIL_PATH.chmod(0o600)
        except OSError:
            pass
        self.mail_first, self.seen_mail = True, set()
        self.mail_wake.set()

    def mail_remove(self):
        MAIL_PATH.unlink(missing_ok=True)
        self.mail = []

    def add_event(self, d: dict):
        title = str(d.get("title", "")).strip()[:200]
        if not title:
            raise ValueError("Введите название")
        dt.date.fromisoformat(d["date"])
        if d.get("time"):
            dt.time.fromisoformat(d["time"])
        lead = d.get("lead")
        ev = {"id": "L" + secrets.token_hex(5), "title": title, "date": d["date"],
              "time": d.get("time") or "", "all_day": bool(d.get("all_day")) or not d.get("time"),
              "location": str(d.get("location", ""))[:200],
              "lead": int(lead) if lead not in (None, "") else None}
        self.local.append(ev)
        self._save_local()

    def delete_event(self, eid: str):
        self.local = [e for e in self.local if e["id"] != eid]
        self._save_local()

    def _save_local(self):
        EVENTS_PATH.write_text(json.dumps(self.local, ensure_ascii=False, indent=1), encoding="utf-8")
        self.rebuild()

    def _mail_loop(self):
        while True:
            acc = self.mail_account()
            if acc or self.g.connected():
                try:
                    msgs = (imap_mail.fetch_unread(acc["email"], acc["password"]) if acc
                            else self.g.unread_mail())
                    fresh = new_mail(msgs, self.seen_mail, self.mail_first)
                    self.mail_first = False
                    if self.cfg["notify_mail"]:
                        for m in fresh:
                            self.alert("Почта: " + m["from"].split("<")[0].strip().strip('"'), m["subject"])
                    self.mail, self.mail_error = msgs, ""
                except Exception as ex:
                    self.mail_error = str(ex)
            self.mail_wake.wait(int(self.cfg["mail_poll_seconds"]) if (acc or self.g.connected()) else 5)
            self.mail_wake.clear()

    def state(self, since=0):
        return {
            "connected": self.g.connected(), "connecting": self.connecting,
            "has_key": Path(self.cfg["credentials_file"]).exists(), "error": self.error,
            "events": [{"id": e["id"], "title": e["summary"], "start": e["start"].isoformat(),
                        "all_day": e["all_day"], "link": e["link"], "location": e["location"],
                        "local": bool(e.get("local"))} for e in self.events],
            "mail": self.mail, "mail_account": self.mail_account().get("email", ""), "mail_error": self.mail_error,
            "alerts": [a for a in self.alerts if a["id"] > since],
            "config": {k: self.cfg[k] for k in EDITABLE} | {"drive_folders": self.cfg["drive_folders"], "local_folders": self.cfg["local_folders"]},
        }

    def save_config(self, data: dict):
        for k in ("calendar_poll_seconds", "mail_poll_seconds", "default_lead_minutes"):
            if k in data:
                self.cfg[k] = max(1, int(data[k]))
        for k in ("notify_calendar", "notify_mail"):
            if k in data:
                self.cfg[k] = bool(data[k])
        if "local_folders" in data:
            self.cfg["local_folders"] = [str(p).strip() for p in data["local_folders"] if str(p).strip()][:20]
        if "drive_folders" in data:
            self.cfg["drive_folders"] = [{"name": str(f["name"])[:60], "id": str(f["id"])}
                                         for f in data["drive_folders"] if re.fullmatch(r"[\w-]+", str(f.get("id", "")))]
        CONFIG_PATH.write_text(yaml.safe_dump(self.cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.wake.set()

    def save_key(self, text: str):
        data = json.loads(text)
        if "installed" not in data and "web" not in data:
            raise ValueError("Это не OAuth-ключ Google (нужен тип «Приложение для ПК»)")
        Path(self.cfg["credentials_file"]).write_text(text, encoding="utf-8")

    def connect(self):
        if self.connecting:
            return
        self.connecting = True

        def run():
            try:
                self.g.connect()
                self.error = ""
                self.wake.set()
            except Exception as ex:
                self.error = str(ex)
            finally:
                self.connecting = False
        threading.Thread(target=run, daemon=True).start()


def make_handler(core: Core):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _auth(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost") and self.headers.get("X-Token") == core.token

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                html = (WEB / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", core.token)
                return self._send(200, html.encode(), "text/html")
            if u.path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if u.path == "/ping":
                return self._send(200, {"ok": True, "version": VERSION})
            if not self._auth():
                return self._send(403, {"error": "forbidden"})
            q = parse_qs(u.query)
            try:
                if u.path == "/api/state":
                    return self._send(200, core.state(int(q.get("since", ["0"])[0])))
                if u.path == "/api/tasks":
                    return self._send(200, core.tasks())
                if u.path == "/api/files":
                    return self._send(200, core.files(q.get("path", [""])[0]))
                if u.path == "/api/drive":
                    fid = q.get("folder", ["root"])[0]
                    if not re.fullmatch(r"[\w-]+", fid):
                        return self._send(400, {"error": "bad folder"})
                    return self._send(200, core.g.drive(fid))
            except Exception as ex:
                return self._send(500, {"error": str(ex)})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._auth():
                return self._send(403, {"error": "forbidden"})
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n).decode("utf-8") if n else ""
            try:
                p = self.path
                if p == "/api/key":
                    core.save_key(raw)
                elif p == "/api/connect":
                    core.connect()
                elif p == "/api/disconnect":
                    core.g.disconnect()
                elif p == "/api/refresh":
                    core.wake.set()
                elif p == "/api/config":
                    core.save_config(json.loads(raw))
                elif p == "/api/notify-test":
                    core.alert("Помощник", "Уведомления работают ✨")
                elif p == "/api/events":
                    core.add_event(json.loads(raw))
                elif p == "/api/events/delete":
                    core.delete_event(str(json.loads(raw)["id"]))
                elif p == "/api/tasks":
                    d = json.loads(raw)
                    core.task_add(str(d["title"])[:500], d.get("due") or "")
                elif p == "/api/tasks/done":
                    core.task_change(str(json.loads(raw)["id"]))
                elif p == "/api/tasks/delete":
                    core.task_change(str(json.loads(raw)["id"]), delete=True)
                elif p == "/api/open":
                    core.open_path(json.loads(raw)["path"])
                elif p == "/api/mail/save":
                    d = json.loads(raw)
                    core.mail_save(str(d.get("email", "")), str(d.get("password", "")))
                elif p == "/api/mail/remove":
                    core.mail_remove()
                elif p == "/api/quit":
                    self._send(200, {"ok": True})
                    threading.Timer(0.3, lambda: __import__("os")._exit(0)).start()
                    return
                else:
                    return self._send(404, {"error": "not found"})
                self._send(200, {"ok": True})
            except Exception as ex:
                self._send(500, {"error": str(ex)})
    return H


def serve(port=8770):
    core = Core()
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(core))
    return core, srv
