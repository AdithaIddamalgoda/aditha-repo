"""X post ingestion. Primary: third-party low-latency feed (WebSocket).
Fallback: official X API v2 polling of the watchlist. Test: replay a JSONL fixture.

The vendor payload schema is NOT pinned here -- `normalize()` accepts a few common
shapes. Capture a real message from your vendor and adapt it (and add a fixture).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ingest")


@dataclass(frozen=True)
class Tweet:
    id: str
    handle: str
    text: str
    created_ts: float       # epoch seconds, author-side timestamp
    received_ts: float      # when we saw it (latency metric)


def _parse_ts(v) -> float:
    if isinstance(v, (int, float)):
        return float(v) / (1000 if v > 1e12 else 1)
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(v, fmt)
            return dt.timestamp() if dt.tzinfo else dt.replace(tzinfo=None).timestamp() - time.timezone
        except (ValueError, TypeError):
            continue
    return time.time()


def normalize(msg: dict) -> list[Tweet]:
    """Accepts {tweets:[...]}, {data:{...}}, or a bare tweet object."""
    items = msg.get("tweets") or ([msg["data"]] if isinstance(msg.get("data"), dict) else [msg])
    out = []
    now = time.time()
    for t in items:
        text = t.get("text") or t.get("full_text") or ""
        author = t.get("author") or t.get("user") or {}
        handle = (author.get("userName") or author.get("username") or author.get("screen_name")
                  or t.get("handle") or "")
        tid = str(t.get("id") or t.get("id_str") or "")
        if not (tid and text and handle):
            continue
        out.append(Tweet(tid, handle, text, _parse_ts(t.get("createdAt") or t.get("created_at")), now))
    return out


def prefilter(t: Tweet, watch: dict) -> bool:
    handles = {a["handle"].lower() for a in watch["accounts"]}
    if t.handle.lower() not in handles:
        return False
    kws = [k.lower() for k in watch.get("keywords", [])]
    return not kws or any(k in t.text.lower() for k in kws)


async def feed_ws(queue: asyncio.Queue, watch: dict) -> None:
    import websockets

    url, key = os.getenv("X_FEED_WS_URL", ""), os.getenv("X_FEED_API_KEY", "")
    if not url or not key:
        log.warning("X feed not configured; WebSocket ingest disabled")
        return
    backoff = 1.0
    while True:
        try:
            async with websockets.connect(url, additional_headers={"x-api-key": key},
                                          ping_interval=20, ping_timeout=20) as ws:
                log.info("feed connected")
                backoff = 1.0
                async for raw in ws:
                    try:
                        for t in normalize(json.loads(raw)):
                            if prefilter(t, watch):
                                queue.put_nowait(t)
                    except (ValueError, KeyError) as e:
                        log.debug("skip malformed message: %s", e)
        except Exception as e:  # noqa: BLE001  reconnect on anything
            log.warning("feed error: %s; retry in %.0fs", e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def poll_official(queue: asyncio.Queue, watch: dict, every: float = 45.0) -> None:
    """Slow safety-net via the official API (pay-per-use reads). Dedupe is in the store."""
    import httpx

    token = os.getenv("X_BEARER_TOKEN", "")
    if not token:
        return
    headers = {"Authorization": f"Bearer {token}"}
    ids: dict[str, str] = {}
    since: dict[str, str] = {}
    async with httpx.AsyncClient(headers=headers, timeout=15) as c:
        while True:
            for acct in watch["accounts"]:
                h = acct["handle"]
                try:
                    if h not in ids:
                        r = await c.get(f"https://api.x.com/2/users/by/username/{h}")
                        ids[h] = r.json()["data"]["id"]
                    params = {"max_results": 5, "tweet.fields": "created_at"}
                    if h in since:
                        params["since_id"] = since[h]
                    r = await c.get(f"https://api.x.com/2/users/{ids[h]}/tweets", params=params)
                    for tw in r.json().get("data", []):
                        since[h] = max(since.get(h, "0"), tw["id"], key=int)
                        t = normalize({"id": tw["id"], "text": tw["text"], "handle": h,
                                       "created_at": tw.get("created_at")})
                        for x in t:
                            if prefilter(x, watch):
                                queue.put_nowait(x)
                except Exception as e:  # noqa: BLE001
                    log.warning("official poll %s failed: %s", h, e)
            await asyncio.sleep(every)


async def replay(queue: asyncio.Queue, path: Path, watch: dict, fresh: bool = True) -> None:
    """Replay JSONL fixture (one raw tweet message per line); `fresh` re-stamps times to now."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        for t in normalize(json.loads(line)):
            if fresh:
                t = Tweet(t.id, t.handle, t.text, time.time(), time.time())
            if prefilter(t, watch):
                await queue.put(t)
