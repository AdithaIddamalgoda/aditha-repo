"""Config loading. YAML for limits/watchlists, environment for secrets."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
KILL_FILE = DATA_DIR / "HALT"
HEARTBEAT_FILE = DATA_DIR / "heartbeat"


def load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:  # dotenv optional in tests
        pass


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def dry_run() -> bool:
    """Default to shadow mode unless DRY_RUN is explicitly '0'."""
    return os.getenv("DRY_RUN", "1") != "0"
