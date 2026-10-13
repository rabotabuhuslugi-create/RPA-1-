"""Запуск помощника: локальный сервер + окно приложения (Edge/Chrome без адресной строки).

    python -m assistant.app
Повторный запуск просто открывает окно уже работающего помощника.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
import webbrowser
from pathlib import Path

from .server import serve

PORT = 8770
URL = f"http://127.0.0.1:{PORT}/"


def find_browser() -> str | None:
    cands = []
    if sys.platform == "win32":
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                cands += [Path(base) / "Microsoft/Edge/Application/msedge.exe",
                          Path(base) / "Google/Chrome/Application/chrome.exe"]
    else:
        cands = [shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge")]
    return next((str(c) for c in cands if c and Path(c).exists()), None)


def open_window():
    exe = find_browser()
    if exe:
        profile = Path.home() / ".assistant_profile"
        subprocess.Popen([exe, f"--app={URL}", "--start-maximized", f"--user-data-dir={profile}",
                          "--no-first-run"])
    else:
        webbrowser.open(URL)


def running() -> bool:
    try:
        return urllib.request.urlopen(URL + "ping", timeout=1).status == 200
    except Exception:
        return False


def main():
    if running():
        open_window()
        return
    core, srv = serve(PORT)
    open_window()
    srv.serve_forever()


if __name__ == "__main__":
    main()
