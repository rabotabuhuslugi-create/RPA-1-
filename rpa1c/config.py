import os
from pathlib import Path

import yaml


def load(path: str = "config.yaml") -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cfg["onec"]["password"] = os.environ.get(cfg["onec"].get("password_env", ""), "")
    for k in cfg["folders"].values():
        Path(k).mkdir(parents=True, exist_ok=True)
    return cfg
