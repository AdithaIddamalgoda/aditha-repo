"""Independent watchdog (separate process/systemd unit). If the orchestrator's
heartbeat goes stale, halt trading and flatten, like a telecom SLA/heartbeat timer.
Because it is a separate process it still works when the orchestrator hangs.
"""
from __future__ import annotations

import logging
import time

from . import notify
from .config import HEARTBEAT_FILE, load_env
from .risk_gate import RiskGate

STALE_AFTER_S = 90
log = logging.getLogger("watchdog")


def flatten_everything() -> None:
    from .config import dry_run
    if dry_run():
        return
    for mod, cls in (("binance_client", "BinanceClient"), ("moomoo_client", "MoomooClient")):
        try:
            m = __import__(f"src.{mod}", fromlist=[cls])
            res = getattr(m, cls)().flatten_all()
            notify.send(f"watchdog flattened {cls}: {res}")
        except Exception as e:  # noqa: BLE001
            notify.send(f"⚠️ watchdog flatten {cls} failed: {e}")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    load_env()
    alerted = False
    while True:
        try:
            age = time.time() - float(HEARTBEAT_FILE.read_text())
        except (FileNotFoundError, ValueError):
            age = float("inf")
        if age > STALE_AFTER_S and not alerted:
            RiskGate.halt("watchdog: heartbeat stale")
            notify.send(f"🚨 heartbeat stale ({age:.0f}s). HALTED; flattening.")
            flatten_everything()
            alerted = True
        elif age <= STALE_AFTER_S:
            alerted = False
        time.sleep(15)


if __name__ == "__main__":
    main()
