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

## Strategy status (2026-10-21): DIP-BUY MODE active

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
