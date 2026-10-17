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
`coins_bought.json`, `cooloffs.json`, `creds.yml`.

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
