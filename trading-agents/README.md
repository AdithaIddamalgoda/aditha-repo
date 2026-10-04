# Multi-agent trading system (Binance + Moomoo + X signals)

Agentic, event-driven trading for a Tencent Cloud VM, driven by headless Claude Code.
**This trades real money. It ships in shadow mode (`DRY_RUN=1`); you must flip it on deliberately. Not financial advice; you can lose the whole stake, and tweet-driven futures trading is high-risk.**

## How it works

```
X feed (WebSocket) ─► prefilter ─► x-signal agent (fast model, JSON)
                                      ─► binance-trader / moomoo-trader agent (JSON proposal)
                                          ─► RISK GATE (Python, hard limits)  ─► exchange adapter
                                                                                   └► audit.db + Telegram
watchdog (separate process): stale heartbeat ─► HALT + flatten      daily-report timer ─► report + Telegram
```

| Agent | Where | Model | Tools |
|---|---|---|---|
| `x-signal` | `.claude/agents/x-signal.md` | haiku (fast) | none |
| `binance-trader` | `.claude/agents/binance-trader.md` | sonnet | none |
| `moomoo-trader` | `.claude/agents/moomoo-trader.md` | sonnet | none |
| `daily-report` | `.claude/agents/daily-report.md` | sonnet | WebSearch/WebFetch (read-only) |

Design rule: **LLMs propose, deterministic code disposes.** Agents run tool-less and only return JSON; every order passes `src/risk_gate.py` (limits in `config/limits.yaml`), which can shrink but never enlarge a proposal. The kill switch is a file (`data/HALT`) plus Telegram `/halt`.

Telecom-ops patterns used: heartbeat + independent watchdog, idempotent client order IDs, reconnect with exponential backoff, signal TTL (staleness), and a CDR-style append-only audit table (`data/audit.db`).

## 1. Choose and prepare the VM
- **Region matters.** Binance.com blocks restricted jurisdictions by IP (mainland China, US, Singapore and others — check Binance's current list). Pick a Tencent region such as Tokyo or Frankfurt, and verify it is allowed for your country of residence/account.
- Ubuntu 22.04+, 2 vCPU/4 GB is plenty. Attach a **static public IP**; allow only SSH (restrict to your IP) inbound. Create a non-root user `trader`.
- Install: `sudo apt install -y python3-venv sqlite3 git unzip`, Node 20+, then Claude Code (`npm i -g @anthropic-ai/claude-code`) and run `claude` once to log in.
- Subscription vs API: you chose the Claude Code CLI. Confirm your plan's terms allow unattended automated use at this call volume; if you hit limits, set an `ANTHROPIC_API_KEY` for the service instead.

## 2. Install
```bash
git clone <this repo> && cd aditha-repo/trading-agents
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env && chmod 600 .env
python -m pytest -q          # 19 tests should pass
claude --help | grep -E "tools|append-system-prompt|output-format"   # verify flags used by src/claude_runner.py
```

## 3. Accounts and keys
**Binance** — use a sub-account (or separate account) funded only with your risk capital.
1. API Management → create key: *Enable Reading*, *Enable Spot & Margin Trading*, *Enable Futures*. **Never enable withdrawals.**
2. Restrict to the VM's static IP. Put keys in `.env`. Start with `BINANCE_TESTNET=1`.
3. Futures: set the account to one-way mode; the code sets isolated margin and leverage per trade.

**Moomoo** — requires OpenAPI enabled for your entity (US/SG/AU/etc.) and a questionnaire/agreement in the app.
1. Download OpenD for Linux from <https://www.moomoo.com/download/OpenAPI>; configure `OpenD.xml` (`ip=127.0.0.1`, `api_port=11111`).
2. Run `./OpenD` once interactively to complete SMS/2FA login, then enable `deploy/opend.service`.
3. Start with `MOOMOO_ENV=SIMULATE`. Adjust `SecurityFirm` in `src/moomoo_client.py` to match your entity. For REAL set `MOOMOO_TRADE_PASSWORD`.

**X feed** — official filtered stream costs $5,000/mo (Pro) and pay-per-use has no stream, so this uses a third-party feed (e.g. twitterapi.io, ~1–5 s latency, ~$0.00015/read). It is unofficial: check its ToS and reliability. Capture a real WebSocket message, adapt `normalize()` in `src/signal_ingest.py`, and add it to `tests/fixtures/`. `X_BEARER_TOKEN` enables the slow official-API polling fallback.

**Telegram** — create a bot with @BotFather; set `TELEGRAM_BOT_TOKEN` and your `TELEGRAM_CHAT_ID`. Commands: `/halt` (halt + flatten), `/resume`, `/status`.

## 4. Configure
- `config/accounts_watchlist.yaml` — handles and keyword prefilter.
- `config/limits.yaml` — per-trade % of equity, leverage cap (3x), mandatory stop-loss, daily-loss halt (3%), trades/day, symbol allowlists.
- `config/symbol_map.yaml` — asset → Binance/Moomoo symbols.

## 5. Bring-up ladder (do not skip rungs)
1. `python -m src.orchestrator --replay tests/fixtures/tweets.jsonl` with `DRY_RUN=1`. Check `data/audit.db` (use the `trade-journal` skill) and the measured tweet→decision latency.
2. Live feed in `DRY_RUN=1` for a day or more; read what it *would* have done.
3. Testnet/simulate with `DRY_RUN=0`, `BINANCE_TESTNET=1`, `MOOMOO_ENV=SIMULATE`. Verify entries, attached stop-losses, and `/halt` flatten.
4. Live with minimum size: `DRY_RUN=0`, `BINANCE_TESTNET=0`, `MOOMOO_ENV=REAL`, small capital. You asked to go live with tiny capital; rungs 1–3 take an hour or two and are strongly recommended first, because the exchange adapters here were written against SDK docs and have **not** been run against live endpoints.

## 6. Run as services
```bash
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/   # edit paths/user first
sudo systemctl daemon-reload
sudo systemctl enable --now opend trader watchdog report.timer
journalctl -u trader -f
```
Stop the watchdog test: `sudo systemctl stop trader` → within ~90 s you should get a Telegram alert and `data/HALT` appears.

## 7. Operating with Claude Code on the VM
Run `claude` in this folder. `CLAUDE.md` forbids placing orders outside the risk gate or editing limits; `.claude/settings.json` denies reading `.env` and editing limits/risk code. Skills: `market-report`, `trade-journal`.

## Reference material (>50K★)
- [anthropics/skills](https://github.com/anthropics/skills) — skill format used in `.claude/skills/`.
- [obra/superpowers](https://github.com/obra/superpowers) — plan→execute/TDD skills worth installing for extending this repo.
- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) — analyst/trader/risk-manager topology this design borrows from.
- [binance/binance-skills-hub](https://github.com/binance/binance-skills-hub) — official Binance agent skills; useful read-only for market data. Avoid unaudited community Binance MCP servers holding trading keys.

## Known limitations / TODO
- Exchange adapters and `claude -p` flags are unverified on live systems; vendor X payload schema is a guess (`normalize()`).
- US market holidays and half-days are not modelled in the Moomoo hours check.
- Realized-PnL recording (`pnl` table) is not yet wired to fills; the daily-loss breaker currently uses equity snapshots only.
- Spot stop-loss is a stop-limit; Moomoo stop orders may not trigger outside regular hours.
- One position per signal; no portfolio-level correlation or news de-duplication across accounts.
