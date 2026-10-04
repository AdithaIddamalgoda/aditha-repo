"""Binance spot + USDT-M futures adapter (ccxt). Thin on purpose: no decisions here.

NOT validated against live endpoints in this repo's CI. First run it with
BINANCE_TESTNET=1 and DRY_RUN=1, and read the ccxt docs for current testnet/demo
endpoints (Binance has changed futures testnet access before).
"""
from __future__ import annotations

import os
import uuid

import ccxt

from .risk_gate import Proposal


class BinanceClient:
    def __init__(self):
        key, secret = os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_API_SECRET", "")
        testnet = os.getenv("BINANCE_TESTNET", "1") != "0"
        common = {"apiKey": key, "secret": secret, "enableRateLimit": True}
        self.spot = ccxt.binance({**common, "options": {"defaultType": "spot"}})
        self.fut = ccxt.binance({**common, "options": {"defaultType": "future"}})
        if testnet:
            self.spot.set_sandbox_mode(True)
            self.fut.set_sandbox_mode(True)

    # -- account snapshot -------------------------------------------------
    def equity_usd(self) -> float:
        """Futures wallet + spot USDT. Extend if you hold other assets spot."""
        total = 0.0
        try:
            total += float(self.fut.fetch_balance()["total"].get("USDT", 0) or 0)
            total += float(self.spot.fetch_balance()["total"].get("USDT", 0) or 0)
        except ccxt.BaseError:
            raise
        return total

    def open_positions(self) -> int:
        pos = self.fut.fetch_positions()
        return sum(1 for p in pos if abs(float(p.get("contracts") or 0)) > 0)

    def price(self, symbol: str, futures: bool) -> float:
        ex = self.fut if futures else self.spot
        return float(ex.fetch_ticker(symbol)["last"])

    # -- execution --------------------------------------------------------
    def execute(self, p: Proposal) -> dict:
        cid = f"ta-{p.signal_id[:12]}-{uuid.uuid4().hex[:8]}"
        if p.venue == "binance_futures":
            return self._futures(p, cid)
        return self._spot(p, cid)

    def _futures(self, p: Proposal, cid: str) -> dict:
        ex = self.fut
        ex.set_margin_mode("isolated", p.symbol)
        ex.set_leverage(p.leverage, p.symbol)
        px = self.price(p.symbol, True)
        amount = float(ex.amount_to_precision(p.symbol, p.notional_usd / px))
        entry = ex.create_order(
            p.symbol, "market", p.side, amount,
            params={"newClientOrderId": cid, "reduceOnly": p.reduce_only},
        )
        out = {"client_id": cid, "entry": entry["id"], "amount": amount}
        if not p.reduce_only:
            exit_side = "sell" if p.side == "buy" else "buy"
            sign = -1 if p.side == "buy" else 1
            if p.stop_loss_pct:
                sl = px * (1 + sign * p.stop_loss_pct / 100)
                ex.create_order(p.symbol, "market", exit_side, amount, params={
                    "stopLossPrice": float(ex.price_to_precision(p.symbol, sl)),
                    "reduceOnly": True, "newClientOrderId": cid + "-sl"})
            if p.take_profit_pct:
                tp = px * (1 - sign * p.take_profit_pct / 100)
                ex.create_order(p.symbol, "market", exit_side, amount, params={
                    "takeProfitPrice": float(ex.price_to_precision(p.symbol, tp)),
                    "reduceOnly": True, "newClientOrderId": cid + "-tp"})
        return out

    def _spot(self, p: Proposal, cid: str) -> dict:
        ex = self.spot
        px = self.price(p.symbol, False)
        amount = float(ex.amount_to_precision(p.symbol, p.notional_usd / px))
        entry = ex.create_order(p.symbol, "market", p.side, amount,
                                params={"newClientOrderId": cid})
        out = {"client_id": cid, "entry": entry["id"], "amount": amount}
        if p.side == "buy" and p.stop_loss_pct:
            sl = px * (1 - p.stop_loss_pct / 100)
            limit = sl * 0.995
            ex.create_order(p.symbol, "limit", "sell", amount,
                            float(ex.price_to_precision(p.symbol, limit)),
                            params={"stopLossPrice": float(ex.price_to_precision(p.symbol, sl)),
                                    "newClientOrderId": cid + "-sl"})
        return out

    def flatten_all(self) -> list[dict]:
        """Emergency: close every futures position at market, cancel open orders."""
        done = []
        for pos in self.fut.fetch_positions():
            amt = float(pos.get("contracts") or 0)
            if abs(amt) <= 0:
                continue
            side = "sell" if pos["side"] == "long" else "buy"
            self.fut.cancel_all_orders(pos["symbol"])
            o = self.fut.create_order(pos["symbol"], "market", side, abs(amt),
                                      params={"reduceOnly": True})
            done.append({"symbol": pos["symbol"], "order": o["id"]})
        return done
