import os
import re
from pathlib import Path

import yaml


def load(path: str = "config.yaml") -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    env = cfg["onec"].get("password_env", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env or ""):
        raise SystemExit(
            "config.yaml: onec.password_env должен содержать ИМЯ переменной окружения "
            "(например ONEC_PASSWORD), а не сам пароль. Пароль задайте так: "
            "$env:ONEC_PASSWORD = 'пароль'"
        )
    cfg["onec"]["password"] = os.environ.get(env, "")
    for k in cfg["folders"].values():
        Path(k).mkdir(parents=True, exist_ok=True)
    return cfg
