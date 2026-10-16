"""Faithful trade-level simulation of the bot's exit logic.

Unlike vectorbt's sl_trail (armed from entry), this replicates
portfolio_manager.update_open_positions_details exactly:

- Entry at the close of the signal candle (1m change >= +2.5%)
- Base SL: entry * (1 - 5%), base TP: entry * (1 + 5%)
- Trailing armed once price reaches +1% (TRAILING_TAKE_PROFIT)
- When armed: SL floor = peak * (1 - 2%), TP trail = peak * (1 + 1%)
  -> position closes when price falls 2% off the peak
  (the bot's min_tp/min_sl converging behaviour is equivalent to a
  2% trailing stop once armed)
- One position per symbol at a time, max TRADE_SLOTS concurrent,
  TRADE_TOTAL USDT per position, TRADING_FEE% each side.
- Per-candle exit check uses high/low; SL checked before TP
  (conservative on ambiguous candles).
"""

import glob
import os
import pickle
import sys

import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Mirror user_data/config.yml
CHANGE_IN_PRICE = 2.5
STOP_LOSS = 5.0
TAKE_PROFIT = 5.0
TRAILING_TAKE_PROFIT = 1.0
TRAILING_STOP_LOSS = 2.0
TRADING_FEE = 0.1
TRADE_TOTAL = 50.0
TRADE_SLOTS = 8
INIT_CASH = TRADE_TOTAL * TRADE_SLOTS
LOOKBACK = 4  # TIME_DIFFERENCE x RECHECK_INTERVAL snapshots, ~1 per minute


def simulate_symbol(sym: str, df: pd.DataFrame):
    """Replay candles, return list of closed trades for one symbol."""
    trades = []
    position = None  # dict with entry state
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    ts = df.index.values

    for i in range(1, len(df)):
        price = closes[i]

        if position is None:
            # Entry signal: range (max-min)/min over the bot's 4-sample
            # window (4 snapshots taken once per ~60s cycle) >= CHANGE_IN_PRICE
            win = closes[max(0, i - LOOKBACK + 1) : i + 1]
            if len(win) == LOOKBACK and (win.max() - win.min()) / win.min() * 100 >= CHANGE_IN_PRICE:
                entry = price
                position = {
                    "entry": entry,
                    "peak": highs[i],
                    "armed": (highs[i] / entry - 1) * 100 >= TRAILING_TAKE_PROFIT,
                    "entry_ts": ts[i],
                }
            continue

        e = position["entry"]
        position["peak"] = max(position["peak"], highs[i])
        if (position["peak"] / e - 1) * 100 >= TRAILING_TAKE_PROFIT:
            position["armed"] = True

        sl_level = e * (1 - STOP_LOSS / 100)
        tp_level = e * (1 + TAKE_PROFIT / 100)
        if position["armed"]:
            sl_level = max(sl_level, position["peak"] * (1 - TRAILING_STOP_LOSS / 100))

        hit_sl = lows[i] <= sl_level
        hit_tp = highs[i] >= tp_level

        exit_price = reason = None
        if hit_sl:
            exit_price, reason = sl_level, ("trailing_sl" if position["armed"] and sl_level > e * (1 - STOP_LOSS / 100) else "sl")
        elif hit_tp:
            exit_price, reason = tp_level, "tp"

        if exit_price is not None:
            gross_ret = exit_price / e - 1
            pnl = TRADE_TOTAL * gross_ret - TRADE_TOTAL * (TRADING_FEE / 100) * 2
            trades.append({
                "symbol": sym,
                "entry_time": position["entry_ts"],
                "exit_time": ts[i],
                "entry": e,
                "exit": exit_price,
                "ret_pct": gross_ret * 100,
                "pnl": pnl,
                "reason": reason,
                "armed": position["armed"],
            })
            position = None

    return trades


def apply_portfolio_constraints(trades: pd.DataFrame):
    """Enforce TRADE_SLOTS concurrency + shared cash, in time order."""
    events = trades.sort_values("entry_time")
    open_pos, accepted, cash = {}, [], INIT_CASH
    for _, t in events.iterrows():
        # close positions that exited before this entry
        for oid, o in list(open_pos.items()):
            if o["exit_time"] <= t["entry_time"]:
                cash += TRADE_TOTAL + o["pnl"]
                del open_pos[oid]
        if len(open_pos) < TRADE_SLOTS and cash >= TRADE_TOTAL:
            cash -= TRADE_TOTAL
            open_pos[id(t)] = t
            accepted.append(t)
    return pd.DataFrame(accepted), cash


def load_frames(path: str) -> dict:
    """Load either a single multi-symbol pkl or a directory of per-symbol pkls."""
    frames = {}
    if os.path.isdir(path):
        for f in sorted(glob.glob(os.path.join(path, "*.pkl"))):
            sym = os.path.basename(f).split("_")[0]
            frames[sym] = pd.read_pickle(f)
    else:
        with open(path, "rb") as fh:
            frames = pickle.load(fh)
    return frames


def main():
    path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.path.join(DATA_DIR, "1m")
    )
    print(f"Loading {path}")
    frames = load_frames(path)

    all_trades = []
    for sym, df in frames.items():
        all_trades.extend(simulate_symbol(sym, df))

    trades = pd.DataFrame(all_trades)
    if trades.empty:
        print("No trades generated.")
        return
    print(f"Raw signals/trades: {len(trades)} across {trades['symbol'].nunique()} symbols")

    trades, final_cash = apply_portfolio_constraints(trades)
    print(f"Executed trades   : {len(trades)} (slots={TRADE_SLOTS}, {TRADE_TOTAL} USDT each)")

    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] <= 0]
    total_pnl = trades["pnl"].sum()
    print(f"\n{'='*60}\nFaithful bot simulation\n{'='*60}")
    print(f"Total PnL          : {total_pnl:.2f} USDT on {INIT_CASH} USDT ({total_pnl/INIT_CASH*100:.2f}%)")
    print(f"Win rate           : {len(wins)/len(trades)*100:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"Avg trade          : {trades['pnl'].mean():.3f} USDT")
    print(f"Best / worst       : {trades['pnl'].max():.2f} / {trades['pnl'].min():.2f} USDT")
    print(f"Profit factor      : {wins['pnl'].sum() / abs(losses['pnl'].sum()) if len(losses) and losses['pnl'].sum() != 0 else float('inf'):.2f}")
    print(f"Avg duration       : {pd.to_timedelta((trades['exit_time'] - trades['entry_time']).mean())}")
    print("\nExit reasons:")
    print(trades["reason"].value_counts().to_string())
    print("\nPnL by symbol:")
    print(trades.groupby("symbol")["pnl"].agg(["sum", "count"]).sort_values("sum").to_string())
    print("\nAll trades:")
    cols = ["symbol", "entry_time", "exit_time", "ret_pct", "pnl", "reason"]
    print(trades[cols].to_string())


if __name__ == "__main__":
    main()
