# Agent notes

## Project

Bitget spot volatility trading bot (CCXT behind `helpers/bitget_client.py` adapter,
UTA mode, USDT pairs). Entrypoint: `bitget_volatility_trading_bot/bitget_volatility_bot.py`.
Config: `user_data/config.yml` (tracked), `user_data/creds.yml` (gitignored, never commit).

Strategy: pump detector - buys coins that moved >= `CHANGE_IN_PRICE`% over
`TIME_DIFFERENCE x RECHECK_INTERVAL` price snapshots (~10s cycle -> 18 snapshots
~= 3min window; top-300 CoinGecko custom list, 24h quote-volume gate
`COINS_MIN/MAX_VOLUME`). Exits: base SL `STOP_LOSS`; trailing arms once a position
reaches `TAKE_PROFIT` (+5%), then sells on a `TRAILING_STOP_LOSS` (1%) retrace
from the recorded max or on a `TRAILING_TAKE_PROFIT` (1%) spike above it.

Guards active in config:
- `MARKET_FILTER_*` - no new buys while `MARKET_FILTER_SYMBOL` (BTCUSDT) is
  <= -3%/24h or dropped >= 1.5% inside the detector window.
- `SESSION_TPSL_OVERRIDE: true` - session = calendar day (since local midnight,
  survives restarts); `SESSION_STOP_LOSS: -2` / `SESSION_TAKE_PROFIT: 5` close
  all positions and stop the bot.
- Post-sell cooloffs: `COOLOFF_BASE_MINUTES: 15` x multipliers, persisted to
  `user_data/cooloffs.json` so restarts don't erase them.

Runtime state in `user_data/` (mounted volume, gitignored): `transactions.db`,
`coins_bought.json`, `cooloffs.json`, `creds.yml`, `session_stop.json`,
`snapshots/` (10s tick recorder, ~60MB/day gz, cron keeps 30 days).

## Strategy status (2026-10-21): PAUSED (dip-mode configured, TRADE_SLOTS 0)

Pump momentum was retired after tick-level replay proved it has no edge
(`backtest/replay_snapshots.py`, `analyze_*.py`, `validate_regime.py` on
5 days, 15M ticks, 307 symbols):
- 44 real post-ring-buffer-fix trades: -184 USDT (WR ~34%).
- Winners/losers statistically identical at entry; 2160-config sweep: zero
  profitable; regime gating (success count, signal density) also fails.
- Root cause: buying at the window max chases tops; this market mean-reverts.

Active strategy (`DIP_MODE_ENABLED: true` in `user_data/config.yml`):
fade fast dumps - signal needs `CHANGE_IN_PRICE`% window range, signed net
<= `DIP_DROP_PCT`, last price within `DIP_NEAR_MIN_PCT` of the window min
and `DIP_BOUNCE_TICKS` non-decreasing tail ticks. Exits are plain TP/SL
(`USE_TRAILING_STOP_LOSS: false`, TAKE_PROFIT 1.0 / STOP_LOSS 4.0).
Tick replay of this shape: ~78% WR, ~+$35-225/week depending on trade
frequency limits - thin edge, keep it in TEST_MODE until proven live.

Dip-mode live sample was ~breakeven and an exact-gate tick replay gave
~$0 over 5 days, so the bot is paused again (`TRADE_SLOTS: 0`, recorder on).

Order blocks (smart-money-concepts `smc.ob()`, causal re-implementation in
`backtest/ob_backtest.py`, 1h, 253 symbols): 4556-config sweep median PF
~0.83; FVG / 4h-structure confluence barely moves it. Best config
(`FROZEN` in the script) made +$857/yr PF 1.17 in-sample but on an unseen
Oct-2023..Oct-2025 holdout returned -$229, PF 0.97, 11/25 positive
months -> no edge. Bitget history candles cap at 200 rows per request
(`fetch_data.py` pages by 200; older 1m caches fetched with 1000 are gappy).

WaveTrend (`backtest/wt_backtest.py`, tune Oct-2023..Oct-2025 = BTC bull,
test Oct-2025..Oct-2026 = BTC bear): pre-registered pick (4h, divergence,
R3) failed the test (PF 1.48 -> 0.62). Post-hoc observation: the family
"4h wt1/wt2 cross-up after osmin <= -50/-60 while the last completed daily
bar has wt1 > wt2" was profitable for every exit variant in both periods
(tune PF 2.0-8.1 on 18-82 trades, test PF 1.07-2.13 on 107-286 trades) -
needs a clean third-period check (pre-Oct-2023) before any live use.
Third-period check (Oct-2022..Oct-2023, 90 symbols, pre-registered in
`HOLDOUT_*`, `--holdout 1h_until1095d`): primary PF 1.11, family median
PF 0.81 -> FAIL. WaveTrend: no robust edge.
`backtest/wt75_backtest.py` (wt1 <= -75 only, no volume; touch/up/cross x
4 filters x 4 exits x 1h/4h, all 3 periods): 0/96 configs profitable in
every period with n>=30; rs_wavetrend.py logic (touch, below EMA200, exit
wt1>60) loses everywhere (PF 0.54-0.92).

Reusable regardless: Bitget/CCXT adapter, risk/loss-limit guards, session
latch, snapshot recorder + tick-level replay simulator, Telegram, deploy
pipeline, test suite.

## Verify changes

Always run the test suite **before every commit/push** - no exceptions:

```
.venv/Scripts/python.exe -m pytest bitget_volatility_trading_bot/tests -x -q
```

Backtest tooling lives in `backtest/` (separate venv `.venv-bt`, data caches and
reports are gitignored).

**User preference: always use vectorbt (`vectorbt` 1.0.0 in `.venv-bt`) for
backtests** - `vbt.Portfolio.from_signals` (or `from_order_func` when exits
need custom logic), fees 0.1%/side, multi-symbol via column-wise DataFrames
with `cash_sharing`/`group_by` for slot-limited portfolios. Hand-rolled
simulators (`ob_backtest.py`, `wt_backtest.py`, `wt75_backtest.py`,
`replay_snapshots.py`) predate this rule; tick-level snapshot replays
(irregular 10s ticks) are the only exception.

## Deployment (ora-1 Oracle VPS, ~1GB RAM)

- Container `bvt_bot` runs TEST_MODE via `deploy/docker-compose.ora1.yml`
  (512M limit, volumes: `user_data/`, `logs/`, `tickerlists/`; `TZ=Europe/Warsaw`).
- **Config-only changes** (mounted `user_data/`): `docker restart bvt_bot` is enough.
- **Code changes** (`*.py`, Dockerfile, requirements): `docker restart` does NOT
  pick them up - the image must be rebuilt:
  `docker compose -f deploy/docker-compose.ora1.yml up -d --build`.
- **After every deploy/rebuild, always remove superseded images:**
  `docker image prune -f` (disk is only 45GB; stale images = hundreds of MB each).
  `deploy/setup-ora1.sh` already does this at the end.
- SSH host alias `ora-1` (user `ubuntu`), repo at `~/bvt`.

## Telegram

Authorized `chat_id` accepts `/status`, `/positions`, `/pause`, `/resume`,
`/sell SYMBOL`, `/changetp[g]`, `/changesl[g]`, `/stop`, `/help`.
Messages use Markdown V1 - keep dynamic values (signal names, reasons)
inside backticks; a bare `_` breaks parsing with a 400 Bad Request.
