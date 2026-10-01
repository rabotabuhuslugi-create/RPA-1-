"""Веб-панель управления роботом (только стандартная библиотека)."""
import json
import shutil
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .ocr import IMAGE_EXT
from .state import State

ALLOWED = IMAGE_EXT | {".pdf"}
MAX_UPLOAD = 50 * 1024 * 1024
HTML = Path(__file__).parent / "web" / "index.html"


def build_state(cfg: dict, st: State) -> dict:
    status = st.get_status()
    poll = cfg["rpa"].get("poll_seconds", 0)
    now = time.time()
    hb = status.get("heartbeat", 0)
    online = bool(hb) and status.get("state") != "stopped" and now - hb < max(2 * poll + 300, 600)
    hist = st.history()
    today = date.today().isoformat()
    t = [h for h in hist if h.get("ts", "").startswith(today)]
    durs = [h["seconds"] for h in hist[-20:] if h.get("seconds")]
    inbox = Path(cfg["folders"]["inbox"])
    errors = Path(cfg["folders"]["errors"])
    ls = lambda p: sorted(f.name for f in p.iterdir() if f.suffix.lower() in ALLOWED) if p.exists() else []
    queue, err_files = ls(inbox), ls(errors)
    return {
        "robot": {
            "online": online,
            "state": "paused" if st.paused() else status.get("state", "offline"),
            "current": status.get("current"),
            "stage": status.get("stage"),
            "started_at": status.get("started_at"),
            "next_run": status.get("next_run"),
            "dry_run": status.get("dry_run", False),
            "paused": st.paused(),
        },
        "now": now,
        "stats": {
            "today": len(t),
            "loaded": sum(h.get("status") == "loaded" for h in t),
            "errors": sum(h.get("status") == "error" for h in t),
            "queue": len(queue),
            "avg_seconds": round(sum(durs) / len(durs), 1) if durs else None,
        },
        "queue": queue,
        "error_files": err_files,
        "recent": list(reversed(hist[-100:])),
        "log": st.log_tail(),
    }


def make_handler(cfg: dict, st: State):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # тишина в консоли
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._json(build_state(cfg, st))
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            name = Path(q.get("name", [""])[0]).name  # защита от ../
            if u.path == "/api/pause":
                st.set_paused(True)
                return self._json({"ok": True})
            if u.path == "/api/resume":
                st.set_paused(False)
                return self._json({"ok": True})
            if u.path == "/api/upload":
                return self._upload(name)
            if u.path == "/api/retry":
                src = Path(cfg["folders"]["errors"]) / name
                if not name or not src.is_file():
                    return self._json({"ok": False, "error": "файл не найден"}, 404)
                shutil.move(src, Path(cfg["folders"]["inbox"]) / name)
                (Path(cfg["folders"]["errors"]) / f"{name}.error.json").unlink(missing_ok=True)
                return self._json({"ok": True})
            self._send(404, b"not found", "text/plain")

        def _upload(self, name: str):
            ext = Path(name).suffix.lower()
            n = int(self.headers.get("Content-Length", 0))
            if not name or ext not in ALLOWED:
                return self._json({"ok": False, "error": "допустимы PDF, JPG, PNG, TIF"}, 400)
            if n <= 0 or n > MAX_UPLOAD:
                return self._json({"ok": False, "error": "размер файла > 50 МБ или пустой"}, 400)
            inbox = Path(cfg["folders"]["inbox"])
            dst = inbox / name
            if dst.exists():
                dst = inbox / f"{dst.stem}_{int(time.time())}{ext}"
            tmp = inbox / (dst.name + ".part")  # робот игнорирует .part
            with tmp.open("wb") as f:
                left = n
                while left:
                    chunk = self.rfile.read(min(65536, left))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            tmp.replace(dst)
            self._json({"ok": True, "name": dst.name})

    return H


def serve(cfg: dict, st: State, block: bool = True) -> ThreadingHTTPServer:
    d = cfg.get("dashboard", {})
    host, port = d.get("host", "127.0.0.1"), int(d.get("port", 8765))
    srv = ThreadingHTTPServer((host, port), make_handler(cfg, st))
    if block:
        srv.serve_forever()
    else:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> None:
    import argparse

    from . import config as cfgmod

    ap = argparse.ArgumentParser(description="Панель управления RPA (без запуска робота)")
    ap.add_argument("-c", "--config", default="config.yaml")
    a = ap.parse_args()
    cfg = cfgmod.load(a.config)
    st = State(cfg["folders"].get("state", "./state"))
    d = cfg.get("dashboard", {})
    print(f"Панель: http://{d.get('host', '127.0.0.1')}:{d.get('port', 8765)}  (Ctrl+C - выход)")
    serve(cfg, st)


if __name__ == "__main__":
    main()
