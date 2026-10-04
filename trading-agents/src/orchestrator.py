"""Always-on supervisor: ingest -> classify -> decide -> RISK GATE -> execute.

Run:  python -m src.orchestrator            (live feed)
      python -m src.orchestrator --replay tests/fixtures/tweets.jsonl   (shadow test)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
import uuid
from pathlib import Path

from . import notify, signal_ingest
from .claude_runner import run_agent
from .config import HEARTBEAT_FILE, DATA_DIR, dry_run, load_env, load_yaml
from .risk_gate import Account, Decision, Proposal, RiskGate
from .store import Store

log = logging.getLogger("orchestrator")


class Trader:
    def __init__(self, replay_path: Path | None):
        self.limits = load_yaml("limits.yaml")
        self.watch = load_yaml("accounts_watchlist.yaml")
        self.symbols = load_yaml("symbol_map.yaml")["assets"]
        self.store = Store()
        self.gate = RiskGate(self.limits, self.store)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.replay_path = replay_path
        self.dry = dry_run()
        self._binance = self._moomoo = None
        self.fast = os.getenv("CLAUDE_FAST_MODEL", "haiku")
        self.big = os.getenv("CLAUDE_TRADER_MODEL", "sonnet")

    # -- lazy adapters (so a Moomoo outage doesn't stop Binance) -----------
    def binance(self):
        if self._binance is None:
            from .binance_client import BinanceClient
            self._binance = BinanceClient()
        return self._binance

    def moomoo(self):
        if self._moomoo is None:
            from .moomoo_client import MoomooClient
            self._moomoo = MoomooClient()
        return self._moomoo

    def account(self, venue: str) -> Account:
        try:
            c = self.moomoo() if venue == "moomoo" else self.binance()
            return Account(c.equity_usd(), c.open_positions())
        except Exception as e:  # noqa: BLE001
            if self.dry:
                log.warning("account snapshot failed (%s); using DRYRUN_EQUITY_USD", e)
                return Account(float(os.getenv("DRYRUN_EQUITY_USD", "1000")), 0)
            raise  # live: never trade on a guessed balance

    # -- pipeline ---------------------------------------------------------
    async def handle(self, t: signal_ingest.Tweet) -> None:
        if not self.store.mark_signal_seen(t.id):
            return
        t0 = time.time()
        self.store.audit("tweet", {"id": t.id, "handle": t.handle, "text": t.text,
                                   "feed_lag_s": round(t.received_ts - t.created_ts, 2)})
        try:
            sig = await run_agent("x-signal", {"handle": t.handle, "text": t.text,
                                               "known_assets": list(self.symbols)},
                                  self.fast, timeout=30)
        except Exception as e:  # noqa: BLE001
            self.store.audit("classify_error", {"id": t.id, "err": str(e)})
            return
        self.store.audit("classification", {"id": t.id, **sig})
        if not sig.get("actionable") or sig.get("asset") not in self.symbols:
            return

        proposal = await self._decide(t, sig)
        if proposal is None:
            return
        acct = self.account(proposal.venue)
        decision = self.gate.check(proposal, acct)
        self.store.audit("risk_decision", {"id": t.id, "approved": decision.approved,
                                           "reasons": decision.reasons, "proposal": decision.proposal.__dict__})
        if not decision.approved:
            notify.send(f"⛔ blocked {proposal.symbol} {proposal.side}: {'; '.join(decision.reasons)}")
            return
        await self._execute(decision, t0)

    async def _decide(self, t, sig) -> Proposal | None:
        asset = sig["asset"]
        venues = {k: v for k, v in self.symbols[asset].items() if v}
        if not venues:
            return None
        agent = "moomoo-trader" if "moomoo" in venues else "binance-trader"
        try:
            d = await run_agent(agent, {"signal": sig, "tweet": {"handle": t.handle, "text": t.text},
                                        "venues": venues,
                                        "limits": {k: self.limits["venues"][k] for k in venues}},
                                self.big, timeout=45)
        except Exception as e:  # noqa: BLE001
            self.store.audit("decide_error", {"id": t.id, "err": str(e)})
            return None
        self.store.audit("trader_decision", {"id": t.id, **d})
        if d.get("action") != "trade" or d.get("venue") not in venues:
            return None
        venue, sym = d["venue"], venues[d["venue"]]
        v = self.limits["venues"][venue]
        acct = self.account(venue)
        lev = int(d.get("leverage", 1) or 1)
        frac = max(0.0, min(1.0, float(d.get("size_fraction", 0.5))))
        notional = acct.equity_usd * v["max_notional_pct_equity"] / 100 * lev * frac
        return Proposal(venue=venue, symbol=sym, side=d["side"], notional_usd=notional,
                        signal_id=t.id, signal_ts=t.created_ts, confidence=float(sig.get("confidence", 0)),
                        leverage=lev, stop_loss_pct=d.get("stop_loss_pct"),
                        take_profit_pct=d.get("take_profit_pct"))

    async def _execute(self, decision: Decision, t0: float) -> None:
        p = decision.proposal
        cid = f"ta-{p.signal_id[:12]}-{uuid.uuid4().hex[:6]}"
        if self.dry:
            self.store.record_order(cid, p.venue, p.symbol, p.side, p.notional_usd, "dry_run", p.signal_id)
            notify.send(f"🧪 DRY RUN {p.venue} {p.side} {p.symbol} ${p.notional_usd:.2f} "
                        f"x{p.leverage} SL{p.stop_loss_pct}% TP{p.take_profit_pct}% "
                        f"(tweet->decision {time.time()-t0:.1f}s)")
            return
        client = self.moomoo() if p.venue == "moomoo" else self.binance()
        try:
            res = await asyncio.to_thread(client.execute, p)
            self.store.record_order(res.get("client_id", cid), p.venue, p.symbol, p.side,
                                    p.notional_usd, "submitted", p.signal_id)
            self.store.audit("order", {"proposal": p.__dict__, "result": res})
            notify.send(f"✅ {p.venue} {p.side} {p.symbol} ${p.notional_usd:.2f} x{p.leverage} "
                        f"({time.time()-t0:.1f}s from tweet). {res}")
        except Exception as e:  # noqa: BLE001
            self.store.record_order(cid, p.venue, p.symbol, p.side, p.notional_usd, "error", p.signal_id)
            self.store.audit("order_error", {"proposal": p.__dict__, "err": str(e)})
            notify.send(f"❌ order failed {p.venue} {p.symbol}: {e}")

    # -- control plane -----------------------------------------------------
    async def on_command(self, cmd: str) -> None:
        if cmd == "/halt":
            RiskGate.halt("telegram /halt")
            notify.send("🛑 HALTED. Flattening all positions…")
            await self.flatten()
        elif cmd == "/resume":
            RiskGate.resume()
            notify.send("▶️ resumed")
        elif cmd == "/status":
            notify.send(f"halted={RiskGate.halted()} dry_run={self.dry} queue={self.queue.qsize()}")

    async def flatten(self) -> None:
        for name, getter in (("binance", self.binance), ("moomoo", self.moomoo)):
            if self.dry:
                continue
            try:
                res = await asyncio.to_thread(getter().flatten_all)
                self.store.audit("flatten", {"venue": name, "result": res})
            except Exception as e:  # noqa: BLE001
                notify.send(f"⚠️ flatten {name} failed: {e}")

    async def heartbeat(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        while True:
            HEARTBEAT_FILE.write_text(str(time.time()))
            await asyncio.sleep(10)

    async def worker(self) -> None:
        while True:
            t = await self.queue.get()
            try:
                await self.handle(t)
            except Exception:  # noqa: BLE001
                log.exception("handle failed")

    async def run(self) -> None:
        notify.send(f"🚀 trader up. dry_run={self.dry}")
        tasks = [self.heartbeat(), notify.poll_commands(self.on_command)]
        tasks += [self.worker() for _ in range(3)]  # parallel LLM calls: tweets don't queue behind each other
        if self.replay_path:
            await signal_ingest.replay(self.queue, self.replay_path, self.watch)
            await asyncio.sleep(1)
            while not self.queue.empty():
                await asyncio.sleep(1)
            await asyncio.sleep(60)  # let in-flight workers finish
            return
        tasks += [signal_ingest.feed_ws(self.queue, self.watch),
                  signal_ingest.poll_official(self.queue, self.watch)]
        await asyncio.gather(*tasks)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", type=Path)
    args = ap.parse_args()
    asyncio.run(Trader(args.replay).run())


if __name__ == "__main__":
    main()
