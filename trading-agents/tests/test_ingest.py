import asyncio
from pathlib import Path

from src.config import load_yaml
from src.signal_ingest import normalize, prefilter, replay

FIX = Path(__file__).parent / "fixtures" / "tweets.jsonl"


def test_normalize_and_prefilter():
    watch = load_yaml("accounts_watchlist.yaml")
    q: asyncio.Queue = asyncio.Queue()
    asyncio.run(replay(q, FIX, watch))
    ids = []
    while not q.empty():
        ids.append(q.get_nowait().id)
    # 1003 has no keyword; 1004 is not a watched account
    assert ids == ["1001", "1002"]


def test_normalize_shapes():
    assert normalize({"tweets": [{"id": 1, "text": "x", "author": {"userName": "a"}}]})[0].handle == "a"
    assert normalize({"data": {"id": 2, "text": "y", "handle": "b"}})[0].id == "2"
    assert normalize({"foo": "bar"}) == []
