"""Telegram alerts + inbound /halt /resume /status polling."""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("notify")


def _creds():
    return os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")


def send(text: str) -> None:
    token, chat = _creds()
    if not token or not chat:
        log.info("[notify] %s", text)
        return
    try:
        httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                   json={"chat_id": chat, "text": text[:4000]}, timeout=10)
    except httpx.HTTPError as e:  # never let alerting crash the trader
        log.warning("telegram send failed: %s", e)


async def poll_commands(on_command, interval: float = 3.0) -> None:
    """Long-poll Telegram; only the configured chat may issue commands."""
    import asyncio

    token, chat = _creds()
    if not token or not chat:
        return
    offset = 0
    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            try:
                r = await client.get(f"https://api.telegram.org/bot{token}/getUpdates",
                                     params={"offset": offset, "timeout": 10})
                for u in r.json().get("result", []):
                    offset = u["update_id"] + 1
                    msg = u.get("message") or {}
                    if str((msg.get("chat") or {}).get("id")) != str(chat):
                        continue
                    text = (msg.get("text") or "").strip()
                    if text.startswith("/"):
                        await on_command(text.split()[0].lower())
            except Exception as e:  # noqa: BLE001
                log.warning("telegram poll error: %s", e)
            await asyncio.sleep(interval)
