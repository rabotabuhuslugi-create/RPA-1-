"""Локальный сервер помощника: Google API + уведомления + современный веб-интерфейс."""
from __future__ import annotations

import datetime as dt
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from .google_api import Google
from .notifier import notify
from .watcher import due_reminders, new_mail, reminder_text

CONFIG_PATH = Path("assistant_config.yaml")
TOKEN_PATH = Path(".assistant_token")
WEB = Path(__file__).parent / "web"
DEFAULTS = {
    "credentials_file": "credentials.json", "token_file": "token.json",
    "calendar_poll_seconds": 60, "mail_poll_seconds": 120, "default_lead_minutes": 10,
    "events_days_ahead": 62, "notify_calendar": True, "notify_mail": True, "drive_folders": [],
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


class Core:
    def __init__(self):
        self.cfg = load_config()
        self.token = get_token()
        self.g = Google(self.cfg["credentials_file"], self.cfg["token_file"])
        self.events, self.mail, self.alerts = [], [], []
        self.seen_rem, self.seen_mail, self.mail_first = set(), set(), True
        self.error, self.connecting = "", False
        self.wake = threading.Event()
        self.lock = threading.Lock()
        for fn in (self._calendar_loop, self._mail_loop):
            threading.Thread(target=fn, daemon=True).start()

    def alert(self, title, text):
        with self.lock:
            self.alerts.append({"id": len(self.alerts) + 1, "title": title, "text": text})
            self.alerts = self.alerts[-50:]
        if not notify(title, text):
            pass  # страница всё равно покажет карточку-уведомление

    def _calendar_loop(self):
        while True:
            if self.g.connected():
                try:
                    evs = self.g.events(days=int(self.cfg["events_days_ahead"]))
                    if self.cfg["notify_calendar"]:
                        for e, left in due_reminders(evs, dt.datetime.now(dt.timezone.utc),
                                                     int(self.cfg["default_lead_minutes"]), self.seen_rem):
                            self.alert("Календарь", reminder_text(e, left))
                    self.events, self.error = evs, ""
                except Exception as ex:
                    self.error = str(ex)
            self.wake.wait(int(self.cfg["calendar_poll_seconds"]) if self.g.connected() else 3)
            self.wake.clear()

    def _mail_loop(self):
        while True:
            if self.g.connected():
                try:
                    msgs = self.g.unread_mail()
                    fresh = new_mail(msgs, self.seen_mail, self.mail_first)
                    self.mail_first = False
                    if self.cfg["notify_mail"]:
                        for m in fresh:
                            self.alert("Почта: " + m["from"].split("<")[0].strip(), m["subject"])
                    self.mail = msgs
                except Exception as ex:
                    self.error = str(ex)
            time.sleep(int(self.cfg["mail_poll_seconds"]) if self.g.connected() else 3)

    def state(self, since=0):
        return {
            "connected": self.g.connected(), "connecting": self.connecting,
            "has_key": Path(self.cfg["credentials_file"]).exists(), "error": self.error,
            "events": [{"id": e["id"], "title": e["summary"], "start": e["start"].isoformat(),
                        "all_day": e["all_day"], "link": e["link"], "location": e["location"]} for e in self.events],
            "mail": self.mail, "alerts": [a for a in self.alerts if a["id"] > since],
            "config": {k: self.cfg[k] for k in EDITABLE} | {"drive_folders": self.cfg["drive_folders"]},
        }

    def save_config(self, data: dict):
        for k in ("calendar_poll_seconds", "mail_poll_seconds", "default_lead_minutes"):
            if k in data:
                self.cfg[k] = max(1, int(data[k]))
        for k in ("notify_calendar", "notify_mail"):
            if k in data:
                self.cfg[k] = bool(data[k])
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
                return self._send(200, {"ok": True})
            if not self._auth():
                return self._send(403, {"error": "forbidden"})
            q = parse_qs(u.query)
            try:
                if u.path == "/api/state":
                    return self._send(200, core.state(int(q.get("since", ["0"])[0])))
                if u.path == "/api/tasks":
                    return self._send(200, core.g.tasks())
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
                elif p == "/api/tasks":
                    d = json.loads(raw)
                    due = dt.date.fromisoformat(d["due"]) if d.get("due") else None
                    core.g.add_task(str(d["title"])[:500], due)
                elif p == "/api/tasks/done":
                    core.g.complete_task(json.loads(raw)["id"])
                elif p == "/api/tasks/delete":
                    core.g.delete_task(json.loads(raw)["id"])
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
