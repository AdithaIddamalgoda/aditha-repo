---
name: trade-journal
description: Review the trading bot's audit log and ledger — per-signal latency, win/loss, blocked-trade reasons, daily PnL. Use when the user asks to review trades, debug why a tweet did or didn't trade, or tune filters.
---
# Trade journal

Source of truth: `data/audit.db` (SQLite, append-only `audit` table plus `orders`, `pnl`).

Useful queries:
- Why was a tweet not traded: `select kind,payload from audit where payload like '%<tweet id>%' order by id;`
  Follow the chain tweet → classification → trader_decision → risk_decision → order.
- Blocked reasons histogram: parse `risk_decision` payloads where `approved=false`.
- Latency: `feed_lag_s` in `tweet` rows (vendor delay) and the "tweet->decision" seconds in alerts.
- Daily PnL: `select date(ts,'unixepoch'),venue,sum(realized) from pnl group by 1,2;`

Report findings plainly (including losing streaks). Propose filter/prompt/limit changes as
diffs for the user to approve; do not apply changes to `config/limits.yaml`.
