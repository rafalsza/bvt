"""Parameter sweep for the pump-detector strategy (numba-accelerated).

Two-stage:
  1. entry: CHANGE_IN_PRICE x LOOKBACK
  2. exit : STOP_LOSS x TAKE_PROFIT x TRAILING_TAKE_PROFIT x TRAILING_STOP_LOSS
     on the best entry configs.

Reports total PnL AND PnL excluding the 2025-10-10..11 flash-crash window
(robustness check — a config that only works on one day is not a strategy).
"""

import os
import sys

import numpy as np
import pandas as pd
from numba import njit

import simulate_faithful as sf

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "1m_binance")
TRADE_TOTAL = 50.0
TRADE_SLOTS = 8
FEE = 0.1

# crash window: 2025-10-10 .. 2025-10-12 UTC
CRASH = (np.datetime64("2025-10-10"), np.datetime64("2025-10-12"))


@njit(cache=True)
def sim_symbol(closes, highs, lows, ts, lookback, change, sl, tp, arm, tdist,
               trade_total, fee_pct):
    """Numba replica of simulate_faithful.simulate_symbol."""
    n = len(closes)
    max_trades = n // 4
    e_ts = np.empty(max_trades, dtype=np.int64)
    x_ts = np.empty(max_trades, dtype=np.int64)
    pnls = np.empty(max_trades, dtype=np.float64)
    cnt = 0

    in_pos = False
    entry = peak = 0.0
    armed = False
    ent_ts = 0

    for i in range(1, n):
        price = closes[i]
        if not in_pos:
            if i >= lookback - 1:
                wmin = closes[i - lookback + 1]
                wmax = wmin
                for j in range(i - lookback + 2, i + 1):
                    if closes[j] < wmin:
                        wmin = closes[j]
                    if closes[j] > wmax:
                        wmax = closes[j]
                if (wmax - wmin) / wmin * 100.0 >= change:
                    entry = price
                    peak = highs[i]
                    armed = (highs[i] / entry - 1.0) * 100.0 >= arm
                    ent_ts = ts[i]
                    in_pos = True
            continue

        if highs[i] > peak:
            peak = highs[i]
        if (peak / entry - 1.0) * 100.0 >= arm:
            armed = True

        sl_level = entry * (1.0 - sl / 100.0)
        tp_level = entry * (1.0 + tp / 100.0)
        if armed:
            t = peak * (1.0 - tdist / 100.0)
            if t > sl_level:
                sl_level = t

        exit_price = 0.0
        exited = False
        if lows[i] <= sl_level:
            exit_price = sl_level
            exited = True
        elif highs[i] >= tp_level:
            exit_price = tp_level
            exited = True

        if exited:
            gross = exit_price / entry - 1.0
            pnl = trade_total * gross - trade_total * (fee_pct / 100.0) * 2.0
            e_ts[cnt] = ent_ts
            x_ts[cnt] = ts[i]
            pnls[cnt] = pnl
            cnt += 1
            in_pos = False

    return e_ts[:cnt], x_ts[:cnt], pnls[:cnt]


def run_config(frames, lookback, change, sl, tp, arm, tdist):
    all_e, all_x, all_p = [], [], []
    for sym, df in frames.items():
        e, x, p = sim_symbol(
            df["close"].values, df["high"].values, df["low"].values,
            df.index.values.astype("datetime64[ns]").astype(np.int64),
            lookback, change, sl, tp, arm, tdist, TRADE_TOTAL, FEE)
        all_e.append(e)
        all_x.append(x)
        all_p.append(p)
    e = np.concatenate(all_e)
    x = np.concatenate(all_x)
    p = np.concatenate(all_p)
    order = np.argsort(e)
    e, x, p = e[order], x[order], p[order]

    # portfolio constraints: slots + shared cash
    open_x = np.empty(TRADE_SLOTS, dtype=np.int64)
    open_x[:] = np.iinfo(np.int64).min
    open_p = np.zeros(TRADE_SLOTS)
    cash = TRADE_TOTAL * TRADE_SLOTS
    acc = np.zeros(len(p), dtype=bool)
    for i in range(len(p)):
        for s in range(TRADE_SLOTS):
            if open_x[s] != np.iinfo(np.int64).min and open_x[s] <= e[i]:
                cash += TRADE_TOTAL + open_p[s]
                open_x[s] = np.iinfo(np.int64).min
        if cash >= TRADE_TOTAL:
            for s in range(TRADE_SLOTS):
                if open_x[s] == np.iinfo(np.int64).min:
                    open_x[s] = e[i]
                    open_p[s] = p[i]
                    cash -= TRADE_TOTAL
                    acc[i] = True
                    break
    return e[acc], p[acc]


def stats(e_ns, pnl):
    total = pnl.sum()
    dt = e_ns.astype("datetime64[ns]")
    ex_crash = pnl[~((dt >= CRASH[0]) & (dt < CRASH[1]))].sum()
    wr = (pnl > 0).mean() * 100 if len(pnl) else 0
    return total, ex_crash, len(pnl), wr


def main():
    frames = sf.load_frames(DATA)
    print(f"{len(frames)} symbols loaded")

    stage = sys.argv[1] if len(sys.argv) > 1 else "entry"

    if stage == "entry":
        results = []
        for lb in [3, 4, 8, 15]:
            for chg in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]:
                e, p = run_config(frames, lb, chg, 5.0, 5.0, 1.0, 2.0)
                tot, ex, n, wr = stats(e, p)
                results.append((lb, chg, n, tot, ex, wr))
                print(f"lookback={lb:2d} chg={chg:.1f}  trades={n:5d}  "
                      f"PnL={tot:+8.2f}  ex-crash={ex:+8.2f}  WR={wr:.0f}%")
        df = pd.DataFrame(results, columns=["lookback", "chg", "trades", "pnl", "ex_crash", "wr"])
        df.to_csv(os.path.join(DATA, "..", "sweep_entry.csv"), index=False)

    elif stage == "exit":
        lb, chg = int(sys.argv[2]), float(sys.argv[3])
        results = []
        for sl in [3.0, 5.0, 7.0]:
            for tp in [3.0, 5.0, 8.0]:
                for arm in [0.5, 1.0, 2.0]:
                    for td in [1.0, 1.5, 2.0, 3.0]:
                        e, p = run_config(frames, lb, chg, sl, tp, arm, td)
                        tot, ex, n, wr = stats(e, p)
                        results.append((sl, tp, arm, td, n, tot, ex, wr))
        df = pd.DataFrame(results, columns=["sl", "tp", "arm", "tdist", "trades", "pnl", "ex_crash", "wr"])
        df = df.sort_values("pnl", ascending=False)
        df.to_csv(os.path.join(DATA, "..", "sweep_exit.csv"), index=False)
        print(df.head(30).to_string(index=False))
        print("\n--- best by ex-crash PnL (robustness) ---")
        print(df.sort_values("ex_crash", ascending=False).head(15).to_string(index=False))


if __name__ == "__main__":
    main()
