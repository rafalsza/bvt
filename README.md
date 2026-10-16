# Bitget Volatility Trading Bot

## Description
This Bitget trading bot analyses the changes in price across coins on Bitget and places trades on the most volatile ones.
In addition, the bot keeps track of all coins bought and sells them according to the configured Stop Loss, Take Profit and trailing rules.

The bot listens to price changes on Bitget spot. By default it only picks USDT pairs from a CoinGecko-ranked top-100 list (`CUSTOM_LIST`), excluding fiat and leveraged token pairs. Open positions outside the list are still tracked and closed normally (pinned symbols).

## How it works (current defaults)

- Every ~60s cycle the bot snapshots prices; a coin that moved more than **2.5%** over the last ~3 snapshots (`CHANGE_IN_PRICE`, `TIME_DIFFERENCE` x `RECHECK_INTERVAL`) triggers a buy
- Position size: `TRADE_TOTAL` USDT, up to `TRADE_SLOTS` concurrent positions
- Exits: base **SL -3%** / **TP +5%**; once price is up **+1%** (`TRAILING_TAKE_PROFIT`) a **1%** trailing stop (`TRAILING_STOP_LOSS`) takes over
- Adaptive cooloff after each sell; session-level TP/SL guard rails
- Taker fee modelled at **0.1%** per side (Bitget standard spot fee; 0.08% if paying fees in BGB - update `TRADING_FEE` accordingly)

> All of this is configurable in `user_data/config.yml`.

## READ BEFORE USE
1. If you set `TEST_MODE: False` in your config, you will be using REAL money.
2. To ensure you do not do this, ALWAYS check the `TEST_MODE` configuration item in config.yml.
3. This is a framework for users to modify and adapt to their overall strategy and needs, and in no way a turn-key solution.
4. Depending on the current market, the default config might not do much, so you will have to adapt it to your own strategy.

## Usage
Configure the bot via `user_data/config.yml` and `user_data/creds.yml` (Bitget API key + secret + passphrase, Telegram optional), then run:

```
cd bitget_volatility_trading_bot
python bitget_volatility_bot.py
```

## Running from docker
1. `docker compose -f docker-compose-new.yml up -d --build` (bot only)
2. `docker-compose up` for the legacy stack with the UI

## VPS deployment (TEST_MODE)
Ready-to-use deployment for an Oracle free-tier VPS lives in `deploy/`:
compose file with memory limits, a setup script (swap + build + start) and
step-by-step instructions in [deploy/DEPLOY.md](deploy/DEPLOY.md).

## Backtesting
`backtest/` contains the research tooling used to validate the strategy:
a faithful trade-level simulator (`simulate_faithful.py`), a numba-accelerated
parameter sweep (`optimize_pump.py`), vectorbt reports (`report_vbt.py`,
`report_pump.py`, `report_compare.py`) and data fetchers for Bitget and the
Binance public archive (historical research only - trading is Bitget-only).

## Tests
```
pytest bitget_volatility_trading_bot/tests
```

## Troubleshooting

1. Read the [FAQ](FAQ.md)
2. Open an issue / check us out on `#troubleshooting` at [Discord](https://discord.gg/buD27Dmvu3)
    - Do not spam, do not berate, we are all humans like you, this is an open source project, not a full time job.

## Disclaimer

All investment strategies and investments involve risk of loss.
**Nothing contained in this program, scripts, code or repository should be construed as investment advice.**
Any reference to an investment's past or potential performance is not,
and should not be construed as, a recommendation or as a guarantee of
any specific outcome or profit.
By using this program you accept all liabilities, and that no claims can be made against the developers or others connected with the program.
