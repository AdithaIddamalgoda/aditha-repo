"""Daily market report. Run by systemd timer (deploy/report.timer).

Unlike the trading agents, the report agent MAY use web tools (read-only research),
but has no exchange access. Output: data/reports/YYYY-MM-DD.md + Telegram digest.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import date

from . import notify
from .claude_runner import run_agent
from .config import DATA_DIR, load_env
from .store import Store


def recent_activity(store: Store, hours: int = 24) -> list[dict]:
    since = time.time() - hours * 3600
    rows = store._db.execute(
        "SELECT ts, kind, payload FROM audit WHERE ts>=? AND kind IN "
        "('classification','risk_decision','order','order_error','flatten') ORDER BY ts", (since,)
    ).fetchall()
    return [{"ts": r[0], "kind": r[1], "payload": json.loads(r[2])} for r in rows][-200:]


async def main() -> None:
    load_env()
    store = Store()
    ctx = {"date": date.today().isoformat(), "bot_activity_24h": recent_activity(store),
           "watchlist": ["BTC", "ETH", "SOL", "DOGE", "SPY", "QQQ", "TSLA", "NVDA"]}
    md = await run_agent("daily-report", ctx, os.getenv("CLAUDE_TRADER_MODEL", "sonnet"),
                         timeout=300, tools="WebSearch,WebFetch")
    out = DATA_DIR / "reports"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{ctx['date']}.md"
    path.write_text(md, encoding="utf-8")
    notify.send(f"📰 Daily report {ctx['date']}\n\n{md[:3500]}")


if __name__ == "__main__":
    asyncio.run(main())
