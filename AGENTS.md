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
~$0 over 5 days, so the bot is paused again (`TRADE_SLOTS: 0`).
Snapshot recording re-enabled on ora-1 on 2026-10-29 (`SNAPSHOT_RECORD: true`)
to gather a fresh out-of-sample tick set for the pump-filter hypothesis
(below). Same day user re-enabled trading (`TRADE_SLOTS: 5`, still TEST_MODE,
dip mode) to collect a parallel live sample; transactions.db was wiped clean
first, so all stats from 2026-10-29 onward are the dip-mode live test.
Pump-filter study (2026-10-29, `backtest/pump_filter_study.py`,
`pump_filter_combo.py`, `pump_filter_phase2.py`; caches `parsed_v2.pkl`,
`events_v2.pkl` include volume+chg24): on 6 days (Oct 17-22) no single
filter saves pump entries, but `pre>=1-2% AND wvol>=5k USDT AND 8-19 UTC`
with SL3/arm5/trail1 gave +33% on ~51 coupled trades — thin, possibly
multiple-testing noise. Hypothesis to validate on the new data, NOT
deployed; filters are not implemented in the bot.

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
wt1>60) loses everywhere (PF 0.54-0.92). vectorbt re-run
(`backtest/wt75_vbt.py`): still 0/96 PASS. Every-signal 4h touch+ob60 is
strong in 2022-23/2023-25 (PF 2.2/1.9, mass rebounds after market-wide
dumps) but loses in 2025-26 (PF 0.86); with 5 shared slots PF 1.28/0.93/0.74.
Bottom confirmation (`backtest/wt75_confirm_vbt.py`: market breadth of
wt1<-60, BTC wt1<-60 or BTC daily WT bull, close above event-bar high):
0/192 pass. Best shape 4h + BTC oversold + xdn0 exit: PF 4.3 / 6.8 / 0.90
- huge in 2022-25, loses in the 2025-26 BTC bear. No confirmation lifts
the worst-period PF.
BTC long-horizon regime (`backtest/wt75_regime_vbt.py`, post-hoc; BTC
daily close > SMA200/SMA100 from `data/btc_1d.pkl`): 0/24 pass. SMA200 is
ON only 20% of 2025-26, so it mostly just stops trading there (n<=48) and
also cuts 2023-25 profits (e.g. ob60 +$20.9k -> -$2.7k).
2026-10-22 exploratory entry/exit matrix (`backtest/wt75_variants_vbt.py`):
5 entries x 5 exits x 1h/4h, BTC and basket, all three already-seen periods.
Uses vectorbt fill-price stop anchoring; equity-based dollar drawdown and
monthly results include open positions. Pivot confirmation delayed 3 bars;
prefix-invariance check passed. No configuration meets PF >=1.1 and n>=30
in every period. Basket 1h divergence + 3R: every-symbol PF 1.095/1.527/1.347,
shared 2500 USDT PF 0.986/0.868/0.800. Shared cash includes fees, so this is
not a strict five-slot implementation. BTC divergence + structure + 2R has
only 2/2/3 trades per period: insufficient evidence. Reports are gitignored
under `backtest/report/wt75_variants/`; regenerate HTML with `--report-only`.
Tight-stop follow-up (`backtest/wt75_tight_vbt.py`): touch/up x SL 1/2/3%
x TP 1.5R/2R or WT1 crossing zero, timeout 24 bars from actual fill using
from_signals callbacks. BTC + basket, 1h/4h, three periods: 0/108 scope/mode
rows pass PF>=1.1 and n>=30 in every period. Best basket every-symbol worst
PF is 0.931 (4h touch, SL3%, TP4.5%); best shared worst PF is 0.827
(4h touch, SL3%, TP6%). Timeout/stop/re-entry/open-priority synthetic checks
pass (`--self-test`). Important limitation: from_signals skips stops on the
entry candle; tight-stop results remain approximate and do not validate live
execution. Timeout 24 bars means 24h on 1h and 96h on 4h. HTML/CSV under
`backtest/report/wt75_tight/`, `--report-only` regenerates the HTML.
`backtest/wt75_bottom_timing.py` is a descriptive event study (not a trade
simulator): signal-candle low vs next 12 candles, missing/gapped windows
excluded. Basket lower lows after -75 occur in 64/74/75% of 1h events and
70/67/78% of 4h events across the three periods. Median lowest-low lag
including signal candle is 2/3/3 bars on 1h and 3/1/3 on 4h. This supports
using -75 as setup activation rather than immediate entry, not profitability
or a fixed optimal delay. Overlapping/correlated events and right-censoring
at bar 12 prevent treating samples as independent confirmed bottoms.
Reports: `backtest/report/wt75_bottom_timing/`.
First-turn study: `wt75_tight_vbt.py --turn` arms on crossing below -75,
then triggers only on the first subsequent WT1 increase (one signal per
crossing, next-open fill). Same nine SL/exit combinations and 24-bar timeout.
0/54 scope/mode rows pass across three periods. Basket shared, SL3%, WT0
exit: 1h PF 0.922/0.632/0.731; 4h PF 0.714/1.139/0.972. BTC 4h same
configuration PF 3.027/1.758/2.798, but only 2/6/4 closed trades: insufficient
sample. First-turn/prefix-causality and timeout checks passed; same entry-bar
stop limitation remains. Reports in `backtest/report/wt75_turn/` compare
against saved tight-study touch/up results. Regenerate with `--turn --report-only`.
User-defined hindsight phase study: `backtest/wt75_phases_vbt.py`, bull
2022-11-20..2025-10-05 inclusive, bear 2025-10-06..2026-07-01 inclusive,
later from 2026-07-02; UTC dates. Merges all three caches (253 symbols,
zero conflicting duplicate OHLC rows), warms indicators on continuous history,
resets capital/positions each phase, values remaining open positions at end.
27 unchanged tight-study combinations per timeframe, BTC + basket. Three
basket every-symbol rows meet PF>=1.1/n>=30 in all phases: 4h touch, WT0
exit, SL1/2/3%. SL3% PF bull/bear/later 1.302/1.110/1.730; same shared
2500 USDT PF 1.030/0.561/2.115. No shared-capital configuration passes.
BTC 4h first-turn/SL3%/WT0 has 7/5/0 trades: too sparse. Hindsight labels,
changing available universe (121 bull, 253 bear/later), correlated signals,
short later phase and entry-bar stop omission prevent live-edge claims.
Reports `backtest/report/wt75_phases/`; `--report-only` rebuilds HTML.
Reused external `C:/python_projects/trading-python/backtest/vectorbt-tests/
wavetrend-backtest/w_params.py` (read-only, parsed via ast.literal_eval) and
10..39 x 10..39 grid in `backtest/wt75_parameter_grid_vbt.py`. Saved per-coin
vs 10/21 uses matched 116 Bitget symbols; full900 grid uses BTC/ETH separately,
1h/4h, touch/first-turn, same user phases. Fixed SL3%, WT0 exit, max24 bars.
This study corrects entry-candle SL omission by two vectorbt execution steps
per candle: open, then OHLC range at synthetic +1ns. Indicators remain on
original bars; callbacks use48 steps for24 bars. Synthetic tests cover
entry-bar SL, timeout and open-exit priority. Intrabar sequence is still unknown.
Saved settings do not give stable shared2500 improvement. Grid0/7200 pass
PF>=1.1/n>=30 every phase, but no candidate has30 trades in every phase;
short later phase limits inference. Among candidates with >=10 trades each
phase, best worst PF is0.858. BTC4h first-turn10/10 has PF1.465/1.107/1.337
on68/23/3 trades; promising-looking but exploratory and too few recent trades.
Reports `backtest/report/wt75_parameter_grid/` include saved source mapping,
per-coin CSVs, full grid, rankings, heatmaps. `--report-only` regenerates HTML.
Earlier study results are not directly comparable: both execution model and
matched universe differ. No external project or VPS trading changes made.
Capital diagnosis `backtest/wt75_capital_vbt.py`: frozen4h WT10/21 touch,
SL3%, WT0/max24bars. Uses vectorbt from_order_func for strict5/10/20 caps,
post-fill state/audit, fee-inclusive500/250/125 entry budgets, entry-bar and
gap-open SL. Tests cover cap, budgets, stops, timeout and identical independent
event reference execution.12 predetermined column orders (alphabetic/reverse/
10 seeded permutations), same2500 reset per user phase, full available universe.
Median marked-to-market net for5/10/20: bull+194/+20/+58; bear-1144/-734/-277;
later+1169/+576/+256 USDT. Every ordering loses in bear for all3 layouts.
Alphabetic5: bull460 accepted/758 cash-blocked; independent complete-window
reference mean return taken+0.039% vs missed+0.395%; bear taken-1.180% vs
missed-0.128%; later taken+2.292% vs missed-1.263%. This is descriptive,
not a causal ranking rule. Concentration: alphabetic5 later closed net+1123,
contribution of best5 symbols+1385; subtracting it leaves-262 (attribution,
not a rerun excluding those coins). Loss of edge is not solved by slot count.
Reports `backtest/report/wt75_capital/` include audit CSVs, event references,
trades, equity and concentration. `--report-only` rebuilds HTML. No deployment.

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
