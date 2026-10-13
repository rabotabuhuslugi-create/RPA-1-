"""Системные уведомления рабочего стола (Windows / macOS / Linux)."""
from __future__ import annotations

import subprocess
import sys


def notify(title: str, message: str) -> bool:
    """Показывает уведомление ОС. True, если получилось."""
    try:
        from plyer import notification
        notification.notify(title=title, message=message[:250], app_name="Помощник", timeout=10)
        return True
    except Exception:
        pass
    try:
        if sys.platform == "darwin":
            subprocess.run(["osascript", "-e",
                            f'display notification "{message}" with title "{title}"'], check=True)
            return True
        if sys.platform.startswith("linux"):
            subprocess.run(["notify-send", title, message], check=True)
            return True
    except Exception:
        pass
    return False
