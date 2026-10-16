"""Backtest the bot's volatility-pump strategy with vectorbt.

Replicates the live logic:
- Entry: close jumps >= CHANGE_IN_PRICE% vs previous 1m candle
  (bot detects max/min over TIME_DIFFERENCE window)
- Exits: base SL -STOP_LOSS%, base TP +TAKE_PROFIT%,
  trailing stop TRAILING_STOP_LOSS% armed at +TRAILING_TAKE_PROFIT%
- Fees: TRADING_FEE% taker per side
- Sizing: TRADE_TOTAL USDT per position, TRADE_SLOTS max positions,
  shared cash pool

Usage: python run_backtest.py [datafile.pkl]
"""

import glob
import os
import pickle
import sys

import numpy as np
import pandas as pd
import vectorbt as vbt

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Mirror user_data/config.yml
CHANGE_IN_PRICE = 2.5        # % jump within TIME_DIFFERENCE to trigger buy
STOP_LOSS = 5.0              # %
TAKE_PROFIT = 5.0            # %
TRAILING_TAKE_PROFIT = 1.0   # % profit that arms the trailing stop
TRAILING_STOP_LOSS = 2.0     # % trail distance
TRADING_FEE = 0.1            # % taker per side
TRADE_TOTAL = 50.0           # USDT per position
TRADE_SLOTS = 8              # max concurrent positions
INIT_CASH = TRADE_TOTAL * TRADE_SLOTS


def load_data(path: str) -> dict:
    with open(path, "rb") as f:
        return pickle.load(f)


def build_panels(frames: dict):
    """Align symbols on a common 1m index -> close/high/low DataFrames."""
    closes, highs, lows = {}, {}, {}
    for sym, df in frames.items():
        closes[sym] = df["close"]
        highs[sym] = df["high"]
        lows[sym] = df["low"]

    idx = pd.concat(closes.values()).index.unique().sort_values()
    close = pd.DataFrame(closes).reindex(idx).ffill()
    high = pd.DataFrame(highs).reindex(idx).ffill()
    low = pd.DataFrame(lows).reindex(idx).ffill()
    return close, high, low


def entry_signals(close: pd.DataFrame) -> pd.DataFrame:
    """Buy when 1m close-to-close change >= CHANGE_IN_PRICE%."""
    pct = close.pct_change() * 100
    return pct >= CHANGE_IN_PRICE


def run(close, high, low, entries, label="", sl_trail=None, sl_stop=None, tp_stop=None):
    sl_stop = STOP_LOSS / 100 if sl_stop is None else sl_stop
    tp_stop = TAKE_PROFIT / 100 if tp_stop is None else tp_stop
    pf = vbt.Portfolio.from_signals(
        close=close,
        open=close,
        high=high,
        low=low,
        entries=entries,
        exits=None,
        price=close,
        sl_stop=sl_stop,
        sl_trail=sl_trail,
        tp_stop=tp_stop,
        fees=TRADING_FEE / 100,
        init_cash=INIT_CASH,
        size=TRADE_TOTAL,
        size_type="value",
        cash_sharing=True,
        group_by=True,
        call_seq="auto",
        ffill_val_price=True,
        freq="1min",
    )

    stats = pf.stats()
    print(f"\n{'='*60}\n{label}\n{'='*60}")
    print(f"Total return       : {stats['Total Return [%]']:.2f}%")
    print(f"Final equity       : {pf.final_value():.2f} USDT (start {INIT_CASH})")
    print(f"Total trades       : {pf.trades.count()}")
    print(f"Win rate           : {stats.get('Win Rate [%]', float('nan')):.1f}%")
    print(f"Profit factor      : {stats.get('Profit Factor', float('nan')):.2f}")
    print(f"Max drawdown       : {stats['Max Drawdown [%]']:.2f}%")
    print(f"Avg trade duration : {stats.get('Avg Winning Trade Duration', 'n/a')}")

    trades = pf.trades.records_readable
    if len(trades):
        pnl_col = "PnL" if "PnL" in trades.columns else "pnl"
        print(f"Avg trade PnL      : {trades[pnl_col].mean():.3f} USDT")
        print(f"Best / worst trade : {trades[pnl_col].max():.2f} / {trades[pnl_col].min():.2f} USDT")
        print("\nTop 5 symbols by trade count:")
        print(trades["Column"].value_counts().head(5).to_string())
        print("\nPnL by symbol (top 5 / bottom 5):")
        by_sym = trades.groupby("Column")[pnl_col].sum().sort_values()
        print(pd.concat([by_sym.head(5), by_sym.tail(5)]).to_string())
    return pf


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(DATA_DIR, "*.pkl")))[-1]
    print(f"Loading {path}")
    frames = load_data(path)
    print(f"{len(frames)} symbols")

    close, high, low = build_panels(frames)
    print(f"Panel: {close.shape[0]} bars x {close.shape[1]} symbols")

    entries = entry_signals(close)
    n_signals = int(entries.sum().sum())
    print(f"Entry signals (>= {CHANGE_IN_PRICE}%/1m): {n_signals}")

    # Variant A: fixed exits only (SL -5% / TP +5%)
    run(close, high, low, entries,
        label="A: fixed SL -5% / TP +5%",
        sl_stop=STOP_LOSS / 100, tp_stop=TAKE_PROFIT / 100)

    # Variant B: trailing 2% armed at entry (approx of bot's arm-at-+1%)
    run(close, high, low, entries,
        label=f"B: trailing {TRAILING_STOP_LOSS}% + TP {TAKE_PROFIT}%",
        sl_stop=TRAILING_STOP_LOSS / 100, sl_trail=True, tp_stop=TAKE_PROFIT / 100)


if __name__ == "__main__":
    main()
