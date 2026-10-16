"""WaveTrend strategy research — entry/exit variant matrix on 1h data.

Entries (on 1h close):
  E1: wt1 crosses UP through -60  + close > EMA200   (dip-buy in uptrend)
  E2: wt1 crosses UP through -60  (no trend filter)
  E3: wt1 crosses UP through -75  + close > EMA200
  E4: wt1 crosses UP through -75  (no filter)
  E5: wt1 crosses above wt2 while wt1 < -40 + close > EMA200 (classic WT buy)

Exits:
  X1: wt1 crosses UP through +60 (overbought) OR SL -10%
  X2: bot exits: TP +5% / SL -5% / trail 2% armed at +1%

Fixed 50 USDT/trade, fee 0.1%, one position per symbol.
"""

import glob
import os
import warnings

import numpy as np
import pandas as pd

import rs_buy_dip_backtest as rb

warnings.filterwarnings("ignore")

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "1m_binance")
TRADE_SIZE, FEE = 50.0, 0.001


def entries_variant(name, wt1, wt2, close, e200):
    up60 = (wt1[1:] >= -60) & (wt1[:-1] < -60)
    up75 = (wt1[1:] >= -75) & (wt1[:-1] < -75)
    wtx = (wt1[1:] > wt2[1:]) & (wt1[:-1] <= wt2[:-1]) & (wt1[1:] < -40)
    above200 = close[1:] > e200[1:]
    if name == "E1": return up60 & above200
    if name == "E2": return up60
    if name == "E3": return up75 & above200
    if name == "E4": return up75
    if name == "E5": return wtx & above200


def exit_variant(name):
    return name


def simulate(sym, h1, entries, exit_mode, params):
    close = h1["close"].values
    high = h1["high"].values
    low = h1["low"].values
    ts = h1.index
    wt1 = params["wt1"]
    trades = []
    pos = None

    for i in range(1, len(close)):
        if pos is None:
            if entries[i - 1]:
                pos = {"e": close[i], "peak": high[i], "armed": False, "ei": i}
            continue
        e = pos["e"]
        pos["peak"] = max(pos["peak"], high[i])
        if (pos["peak"] / e - 1) * 100 >= 1.0:
            pos["armed"] = True

        xp = reason = None
        if exit_mode == "X1":
            if low[i] <= e * 0.90:
                xp, reason = e * 0.90, "sl10"
            elif wt1[i] >= 60 and wt1[i - 1] < 60:
                xp, reason = close[i], "wt_ob"
        else:  # X2 bot exits on 1h
            sl = e * 0.95
            if pos["armed"]:
                sl = max(sl, pos["peak"] * 0.98)
            if low[i] <= sl:
                xp = sl
                reason = "trail" if pos["armed"] and sl > e * 0.95 else "sl"
            elif high[i] >= e * 1.05:
                xp, reason = e * 1.05, "tp"

        if xp is not None:
            r = xp / e - 1
            trades.append({
                "symbol": sym, "entry_time": ts[pos["ei"]], "exit_time": ts[i],
                "ret_pct": r * 100, "pnl": TRADE_SIZE * r - TRADE_SIZE * FEE * 2,
                "reason": reason,
            })
            pos = None
    return trades


def main():
    frames = {
        os.path.basename(f).split("_")[0]: pd.read_pickle(f)
        for f in sorted(glob.glob(os.path.join(DATA, "*.pkl")))
    }
    results = {}
    all_trades = {}
    for variant in ["E1", "E2", "E3", "E4", "E5"]:
        for exit_mode in ["X1", "X2"]:
            key = f"{variant}/{exit_mode}"
            trades = []
            for sym, df_1m in frames.items():
                h1 = rb.resample(df_1m, "1h")
                if len(h1) < 300:
                    continue
                n1, n2 = rb.WAVETREND_PARAMS.get(sym, (10, 21))
                wt1 = rb.wavetrend(h1["high"].values, h1["low"].values,
                                   h1["close"].values, n1, n2)
                wt2 = pd.Series(wt1).rolling(4).mean().values
                e200 = rb.ema(h1["close"].values, 200)
                ent = entries_variant(variant, wt1, wt2, h1["close"].values, e200)
                trades += simulate(sym, h1, ent, exit_mode, {"wt1": wt1})
            all_trades[key] = pd.DataFrame(trades)
            t = all_trades[key]
            if t.empty:
                results[key] = ("0", "-", "-", "-")
                continue
            w = t[t.pnl > 0]; l = t[t.pnl <= 0]
            pf = w.pnl.sum() / abs(l.pnl.sum()) if len(l) and l.pnl.sum() != 0 else float("inf")
            results[key] = (len(t), t.pnl.sum(), len(w) / len(t) * 100, pf)

    print(f"{'variant':8} {'trades':>7} {'PnL USDT':>10} {'WR%':>7} {'PF':>6}")
    for k, (n, pnl, wr, pf) in results.items():
        print(f"{k:8} {n:>7} {pnl:>10.2f} {wr:>6.1f} {pf:>6.2f}")

    # monthly for the best variant
    best = max(results, key=lambda k: results[k][1] if results[k][1] != "-" else -1e9)
    print(f"\n=== Best: {best} ===")
    t = all_trades[best].copy()
    t["month"] = pd.to_datetime(t["entry_time"]).dt.to_period("M")
    print(t.groupby("month")["pnl"].agg(["sum", "count"]).round(2).to_string())


if __name__ == "__main__":
    main()
