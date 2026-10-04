"""Moomoo adapter over the OpenD gateway (moomoo-api SDK). Long-only US equities.

Prereqs on the VM: OpenD running (see deploy/opend.service), logged in once
interactively (SMS/2FA), and MOOMOO_TRADE_PASSWORD set for REAL env.
Start with MOOMOO_ENV=SIMULATE. Not exercised against a live gateway in CI.
"""
from __future__ import annotations

import os

from .risk_gate import Proposal


class MoomooClient:
    def __init__(self):
        from moomoo import (OpenQuoteContext, OpenSecTradeContext, RET_OK,
                            SecurityFirm, TrdEnv, TrdMarket)

        self._RET_OK = RET_OK
        host, port = os.getenv("MOOMOO_HOST", "127.0.0.1"), int(os.getenv("MOOMOO_PORT", "11111"))
        self.env = TrdEnv.REAL if os.getenv("MOOMOO_ENV", "SIMULATE") == "REAL" else TrdEnv.SIMULATE
        self.quote = OpenQuoteContext(host=host, port=port)
        self.trade = OpenSecTradeContext(
            filter_trdmarket=getattr(TrdMarket, os.getenv("MOOMOO_MARKET", "US")),
            host=host, port=port, security_firm=SecurityFirm.FUTUINC)  # adjust to your entity
        if self.env == TrdEnv.REAL:
            ret, msg = self.trade.unlock_trade(os.getenv("MOOMOO_TRADE_PASSWORD", ""))
            if ret != RET_OK:
                raise RuntimeError(f"unlock_trade failed: {msg}")

    def equity_usd(self) -> float:
        ret, data = self.trade.accinfo_query(trd_env=self.env)
        if ret != self._RET_OK:
            raise RuntimeError(f"accinfo_query: {data}")
        return float(data["total_assets"][0])

    def open_positions(self) -> int:
        ret, data = self.trade.position_list_query(trd_env=self.env)
        if ret != self._RET_OK:
            raise RuntimeError(f"position_list_query: {data}")
        return int((data["qty"] > 0).sum())

    def price(self, code: str) -> float:
        ret, data = self.quote.get_market_snapshot([code])
        if ret != self._RET_OK:
            raise RuntimeError(f"snapshot: {data}")
        return float(data["last_price"][0])

    def execute(self, p: Proposal) -> dict:
        from moomoo import OrderType, TrdSide

        px = self.price(p.symbol)
        qty = int(p.notional_usd // px)
        if qty < 1:
            raise ValueError(f"notional {p.notional_usd} too small for 1 share at {px}")
        side = TrdSide.BUY if p.side == "buy" else TrdSide.SELL
        ret, data = self.trade.place_order(
            price=px, qty=qty, code=p.symbol, trd_side=side,
            order_type=OrderType.NORMAL,  # marketable limit at last; use MARKET if you accept slippage
            trd_env=self.env, remark=f"ta-{p.signal_id[:12]}")
        if ret != self._RET_OK:
            raise RuntimeError(f"place_order: {data}")
        out = {"order_id": str(data["order_id"][0]), "qty": qty}
        if p.side == "buy" and p.stop_loss_pct:
            sl = round(px * (1 - p.stop_loss_pct / 100), 2)
            ret, d2 = self.trade.place_order(
                price=sl, qty=qty, code=p.symbol, trd_side=TrdSide.SELL,
                order_type=OrderType.STOP, aux_price=sl, trd_env=self.env,
                remark=f"ta-sl-{p.signal_id[:10]}")
            out["stop"] = str(d2["order_id"][0]) if ret == self._RET_OK else f"FAILED: {d2}"
        return out

    def flatten_all(self) -> list[dict]:
        from moomoo import OrderType, TrdSide

        ret, data = self.trade.position_list_query(trd_env=self.env)
        if ret != self._RET_OK:
            raise RuntimeError(f"position_list_query: {data}")
        done = []
        for _, row in data[data["qty"] > 0].iterrows():
            px = self.price(row["code"])
            r, d = self.trade.place_order(price=px * 0.99, qty=int(row["qty"]), code=row["code"],
                                          trd_side=TrdSide.SELL, order_type=OrderType.NORMAL,
                                          trd_env=self.env)
            done.append({"code": row["code"], "ok": r == self._RET_OK})
        return done

    def close(self):
        self.quote.close()
        self.trade.close()
