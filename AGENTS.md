# Agent notes

## Project

Bitget spot volatility trading bot (CCXT behind `helpers/bitget_client.py` adapter,
UTA mode, USDT pairs). Entrypoint: `bitget_volatility_trading_bot/bitget_volatility_bot.py`.
Config: `user_data/config.yml` (tracked), `user_data/creds.yml` (gitignored, never commit).

Strategy: pump detector - buys coins that moved >= `CHANGE_IN_PRICE`% over
`TIME_DIFFERENCE x RECHECK_INTERVAL` price snapshots (top-100 CoinGecko custom list,
24h quote-volume gate `COINS_MIN/MAX_VOLUME`). Exits: SL/TP + trailing armed at
`TRAILING_TAKE_PROFIT`, distance `TRAILING_STOP_LOSS`.

## Verify changes

```
.venv/Scripts/python.exe -m pytest bitget_volatility_trading_bot/tests -x -q
```

Backtest tooling lives in `backtest/` (separate venv `.venv-bt`, data caches and
reports are gitignored).

## Deployment (ora-1 Oracle VPS, ~1GB RAM)

- Container `bvt_bot` runs TEST_MODE via `deploy/docker-compose.ora1.yml`
  (512M limit, volumes: `user_data/`, `logs/`).
- Update flow: `git pull` -> `docker compose -f deploy/docker-compose.ora1.yml up -d --build`.
- **After every deploy/rebuild, always remove superseded images:**
  `docker image prune -f` (disk is only 45GB; stale images = hundreds of MB each).
  `deploy/setup-ora1.sh` already does this at the end.
- SSH host alias `ora-1` (user `ubuntu`), repo at `~/bvt`.
