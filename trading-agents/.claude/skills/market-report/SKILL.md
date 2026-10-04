---
name: market-report
description: Generate an on-demand market report (crypto, US equities, macro, telecom sector) and review the bot's recent trades. Use when the user asks for a market update, morning brief, or "how did the bot do".
---
# Market report

1. Run `python -m src.report` for the scheduled-style report, or follow the `daily-report`
   agent structure in `.claude/agents/daily-report.md` interactively.
2. Read `data/audit.db` (tables `audit`, `orders`, `pnl`) for the bot's activity:
   `sqlite3 data/audit.db "select datetime(ts,'unixepoch'),kind,payload from audit order by id desc limit 50"`.
3. Cite sources with links, state dates, flag unverified claims.
4. Suggest config changes as text only. Never edit `config/limits.yaml` on your own initiative.
