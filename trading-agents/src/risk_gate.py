"""Deterministic risk gate. Every order proposal -- from an LLM or a rule -- must
pass through RiskGate.check() before any exchange adapter is called. The LLM
cannot modify limits; they come from config/limits.yaml.

The gate may *shrink* a proposal (notional/leverage) but never enlarge it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .config import KILL_FILE
from .store import Store

VENUES = ("binance_spot", "binance_futures", "moomoo")


@dataclass(frozen=True)
class Proposal:
    venue: str                    # binance_spot | binance_futures | moomoo
    symbol: str                   # venue-native symbol
    side: str                     # buy | sell
    notional_usd: float           # position value (margin * leverage for futures)
    signal_id: str
    signal_ts: float              # epoch seconds of the originating post
    confidence: float
    leverage: int = 1
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    reduce_only: bool = False     # exits are always allowed (subject to kill/venue checks)


@dataclass
class Decision:
    approved: bool
    proposal: Proposal
    reasons: list[str] = field(default_factory=list)


@dataclass
class Account:
    """Snapshot supplied by the caller from the exchange adapters."""
    equity_usd: float
    open_positions: int


class RiskGate:
    def __init__(self, limits: dict, store: Store, clock=time.time):
        self.limits = limits
        self.store = store
        self.clock = clock

    # -- kill switch ------------------------------------------------------
    @staticmethod
    def halted() -> bool:
        return KILL_FILE.exists()

    @staticmethod
    def halt(reason: str = "") -> None:
        KILL_FILE.parent.mkdir(parents=True, exist_ok=True)
        KILL_FILE.write_text(reason or "halt")

    @staticmethod
    def resume() -> None:
        KILL_FILE.unlink(missing_ok=True)

    # -- daily-loss breaker ----------------------------------------------
    def daily_loss_breached(self, account: Account) -> bool:
        day = datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y-%m-%d")
        start = self.store.day_start_equity(day)
        if start is None:
            self.store.set_day_start_equity(day, account.equity_usd)
            return False
        loss_pct = (start - account.equity_usd) / start * 100 if start > 0 else 0.0
        return loss_pct >= self.limits["global"]["max_daily_loss_pct"]

    @staticmethod
    def _us_regular_hours(ts: float) -> bool:
        """Mon-Fri 09:30-16:00 America/New_York (US market holidays are NOT modelled)."""
        et = datetime.fromtimestamp(ts, ZoneInfo("America/New_York"))
        if et.weekday() >= 5:
            return False
        return (9, 30) <= (et.hour, et.minute) < (16, 0)

    # -- main check -------------------------------------------------------
    def check(self, p: Proposal, account: Account) -> Decision:
        g = self.limits["global"]
        v = self.limits["venues"].get(p.venue)
        reasons: list[str] = []
        now = self.clock()

        if p.venue not in VENUES or v is None:
            return Decision(False, p, [f"unknown venue {p.venue}"])
        if self.halted():
            reasons.append("kill switch active")
        if not v.get("enabled", False):
            reasons.append(f"{p.venue} disabled")
        if p.side not in ("buy", "sell"):
            reasons.append(f"bad side {p.side}")
        if p.symbol not in v["symbol_allowlist"]:
            reasons.append(f"{p.symbol} not in allowlist")
        if account.equity_usd <= 0:
            reasons.append("non-positive equity")

        # Exits that only reduce exposure bypass entry-only checks (but not the kill
        # switch / allowlist / venue checks above, which still apply).
        if p.reduce_only:
            return Decision(not reasons, p, reasons)

        if self.daily_loss_breached(account):
            reasons.append("daily loss limit breached")
        if p.confidence < g["min_confidence"]:
            reasons.append(f"confidence {p.confidence:.2f} < {g['min_confidence']}")
        if now - p.signal_ts > g["signal_ttl_seconds"]:
            reasons.append(f"signal stale ({now - p.signal_ts:.0f}s)")
        if account.open_positions >= g["max_open_positions"]:
            reasons.append("max open positions")
        day_start = now - (now % 86400)
        if self.store.trades_since(day_start) >= g["max_trades_per_day"]:
            reasons.append("max trades/day")
        last = self.store.last_trade_ts(p.symbol)
        if last is not None and now - last < g["cooldown_seconds_per_symbol"]:
            reasons.append("symbol cooldown")

        if p.side == "sell" and not v.get("allow_short", False):
            reasons.append("shorting not allowed on venue")

        if v.get("regular_hours_only") and not self._us_regular_hours(now):
            reasons.append("outside US regular trading hours")

        if v.get("require_stop_loss"):
            if not p.stop_loss_pct or p.stop_loss_pct <= 0:
                reasons.append("stop loss required")
            elif p.stop_loss_pct > v["max_stop_loss_pct"]:
                reasons.append(f"stop loss {p.stop_loss_pct}% > max {v['max_stop_loss_pct']}%")

        if p.leverage < 1:
            reasons.append("leverage < 1")
        max_lev = v.get("max_leverage", 1)
        adjusted = p
        if p.leverage > max_lev:
            adjusted = replace(adjusted, leverage=max_lev)  # shrink, don't reject

        # Size: margin (notional / leverage) capped at % of equity.
        cap_margin = account.equity_usd * v["max_notional_pct_equity"] / 100.0
        margin = adjusted.notional_usd / adjusted.leverage
        if margin > cap_margin:
            adjusted = replace(adjusted, notional_usd=cap_margin * adjusted.leverage)
        if adjusted.notional_usd <= 0:
            reasons.append("non-positive notional")

        return Decision(not reasons, adjusted if not reasons else p, reasons)
