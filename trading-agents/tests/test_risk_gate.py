import time

import pytest

from src import config
from src.risk_gate import Account, Proposal, RiskGate
from src.store import Store

LIMITS = {
    "global": {
        "max_daily_loss_pct": 3.0, "max_trades_per_day": 2, "max_open_positions": 2,
        "signal_ttl_seconds": 90, "min_confidence": 0.7, "cooldown_seconds_per_symbol": 300,
    },
    "venues": {
        "binance_futures": {
            "enabled": True, "max_notional_pct_equity": 2.0, "max_leverage": 3,
            "symbol_allowlist": ["BTC/USDT:USDT"], "allow_short": True,
            "require_stop_loss": True, "max_stop_loss_pct": 4.0,
        },
        "binance_spot": {
            "enabled": True, "max_notional_pct_equity": 2.0,
            "symbol_allowlist": ["BTC/USDT"], "allow_short": False,
        },
        "moomoo": {
            "enabled": False, "max_notional_pct_equity": 2.0,
            "symbol_allowlist": ["US.TSLA"], "allow_short": False,
            "require_stop_loss": True, "max_stop_loss_pct": 5.0,
        },
    },
}


@pytest.fixture(autouse=True)
def tmp_kill(tmp_path, monkeypatch):
    monkeypatch.setattr("src.risk_gate.KILL_FILE", tmp_path / "HALT")
    monkeypatch.setattr(config, "KILL_FILE", tmp_path / "HALT")


@pytest.fixture
def gate():
    return RiskGate(LIMITS, Store(":memory:"))


ACCT = Account(equity_usd=1000.0, open_positions=0)


def prop(**kw):
    base = dict(venue="binance_futures", symbol="BTC/USDT:USDT", side="buy",
                notional_usd=10.0, signal_id="s1", signal_ts=time.time(),
                confidence=0.9, leverage=1, stop_loss_pct=2.0)
    base.update(kw)
    return Proposal(**base)


def test_happy_path(gate):
    d = gate.check(prop(), ACCT)
    assert d.approved, d.reasons


def test_oversize_is_shrunk_not_rejected(gate):
    d = gate.check(prop(notional_usd=500.0), ACCT)
    assert d.approved
    assert d.proposal.notional_usd == pytest.approx(20.0)  # 2% of 1000


def test_leverage_capped_and_margin_cap_applies(gate):
    d = gate.check(prop(notional_usd=1000.0, leverage=10), ACCT)
    assert d.approved
    assert d.proposal.leverage == 3
    assert d.proposal.notional_usd == pytest.approx(20.0 * 3)


def test_stale_signal_rejected(gate):
    d = gate.check(prop(signal_ts=time.time() - 200), ACCT)
    assert not d.approved and any("stale" in r for r in d.reasons)


def test_low_confidence_rejected(gate):
    assert not gate.check(prop(confidence=0.5), ACCT).approved


def test_missing_stop_loss_rejected(gate):
    assert not gate.check(prop(stop_loss_pct=None), ACCT).approved


def test_excessive_stop_loss_rejected(gate):
    assert not gate.check(prop(stop_loss_pct=9.0), ACCT).approved


def test_symbol_not_allowlisted(gate):
    assert not gate.check(prop(symbol="XRP/USDT:USDT"), ACCT).approved


def test_disabled_venue(gate):
    assert not gate.check(prop(venue="moomoo", symbol="US.TSLA"), ACCT).approved


def test_spot_short_rejected(gate):
    d = gate.check(prop(venue="binance_spot", symbol="BTC/USDT", side="sell"), ACCT)
    assert not d.approved


def test_kill_switch_blocks_everything_including_exits(gate):
    gate.halt("test")
    assert not gate.check(prop(), ACCT).approved
    assert not gate.check(prop(reduce_only=True, side="sell"), ACCT).approved
    gate.resume()
    assert gate.check(prop(), ACCT).approved


def test_reduce_only_skips_entry_checks(gate):
    d = gate.check(prop(reduce_only=True, side="sell", confidence=0.0,
                        signal_ts=0, stop_loss_pct=None), ACCT)
    assert d.approved


def test_max_open_positions(gate):
    assert not gate.check(prop(), Account(1000.0, open_positions=2)).approved


def test_trades_per_day_and_cooldown(gate):
    gate.store.record_order("c1", "binance_futures", "BTC/USDT:USDT", "buy", 10, "dry_run")
    d = gate.check(prop(), ACCT)
    assert not d.approved and any("cooldown" in r for r in d.reasons)
    gate.store.record_order("c2", "binance_futures", "ETH/USDT:USDT", "buy", 10, "dry_run")
    d = gate.check(prop(symbol="BTC/USDT:USDT"), ACCT)
    assert any("max trades" in r for r in d.reasons)


def test_daily_loss_breaker(gate):
    assert gate.check(prop(), Account(1000.0, 0)).approved       # records day start
    d = gate.check(prop(signal_id="s2"), Account(960.0, 0))       # -4% > 3%
    assert not d.approved and any("daily loss" in r for r in d.reasons)


def test_duplicate_signal_ledger(gate):
    assert gate.store.mark_signal_seen("abc") is True
    assert gate.store.mark_signal_seen("abc") is False


def test_moomoo_regular_hours():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    limits = {**LIMITS, "venues": {**LIMITS["venues"], "moomoo": {
        **LIMITS["venues"]["moomoo"], "enabled": True, "regular_hours_only": True}}}
    open_ts = datetime(2026, 10, 5, 10, 0, tzinfo=ZoneInfo("America/New_York")).timestamp()  # Monday
    closed_ts = datetime(2026, 10, 5, 20, 0, tzinfo=ZoneInfo("America/New_York")).timestamp()
    sat_ts = datetime(2026, 10, 3, 11, 0, tzinfo=ZoneInfo("America/New_York")).timestamp()
    def mk(now):
        return RiskGate(limits, Store(":memory:"), clock=lambda: now)
    kw = dict(venue="moomoo", symbol="US.TSLA")
    assert mk(open_ts).check(prop(signal_ts=open_ts, **kw), ACCT).approved
    assert not mk(closed_ts).check(prop(signal_ts=closed_ts, **kw), ACCT).approved
    assert not mk(sat_ts).check(prop(signal_ts=sat_ts, **kw), ACCT).approved
