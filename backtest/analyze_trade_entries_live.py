#!/usr/bin/env python3
"""Entry-quality autopsy for live trades (local run).

Streams snapshot_data_live/*.csv.gz keeping only traded symbols.
Per trade: MFE/MAE until sell, time-to-MFE, and window context at entry
(net, range, pretrend, window volume). Answers whether the +5% arm is
reachable and what flat-TP profile would capture winners.
"""
import csv
import glob
import gzip
import os
import sqlite3
from collections import defaultdict
from datetime import datetime

N = 18
HERE = os.path.dirname(__file__)
DATA_DIR = os.path.join(HERE, "snapshot_data_live")
DB = os.path.join(DATA_DIR, "transactions_live.db")


def ep(s):
    return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").timestamp())


def ep_db(s):
    return int(datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").timestamp())


def main():
    conn = sqlite3.connect(DB)
    trades = conn.execute(
        "select symbol, buy_time, bought_at, sell_time, sold_at, "
        "profit_dollars, sell_reason, closed from transactions "
        "order by buy_time"
    ).fetchall()
    syms = {t[0] for t in trades}
    print(f"{len(trades)} trades over {len(syms)} symbols", flush=True)

    ticks = defaultdict(list)  # sym -> (ep, price, vol)
    for fn in sorted(glob.glob(os.path.join(DATA_DIR, "*.csv.gz"))):
        print("parsing", os.path.basename(fn), flush=True)
        with gzip.open(fn, "rt") as f:
            for r in csv.reader(f):
                if len(r) < 5 or r[1] not in syms:
                    continue
                try:
                    ticks[r[1]].append((ep(r[0]), float(r[2]), float(r[3] or 0)))
                except (ValueError, IndexError):
                    continue
    for s in ticks:
        ticks[s].sort()

    buckets = {t: 0 for t in (1, 2, 3, 4, 5, 6, 8, 10, 15, 20)}
    rows = []
    skipped = []
    for sym, bt, bought, st, sold, pnl, reason, closed in trades:
        series = ticks.get(sym)
        bep = ep_db(bt)
        if not series:
            skipped.append(sym)
            continue
        # find first tick >= buy time
        lo, hi = 0, len(series) - 1
        idx = None
        for j, (e, p, v) in enumerate(series):
            if e >= bep - 5:
                idx = j
                break
        if idx is None:
            skipped.append(sym)
            continue
        net = rng = pre = wvol = None
        if idx >= N:
            w = [x[1] for x in series[idx - N + 1: idx + 1]]
            rng = (max(w) - min(w)) / min(w) * 100
            net = (w[-1] - w[0]) / w[0] * 100
            wvol = series[idx][2] - series[idx - N][2]
        if idx >= 2 * N:
            pw = [x[1] for x in series[idx - 2 * N + 1: idx - N + 1]]
            pre = (pw[-1] - pw[0]) / pw[0] * 100
        sep = ep_db(st) if (st and closed) else None
        mfe = mae = 0.0
        mfe_i = idx
        for j in range(idx + 1, len(series)):
            if sep is not None and series[j][0] > sep:
                break
            d = (series[j][1] - bought) / bought * 100
            if d > mfe:
                mfe, mfe_i = d, j
            if d < mae:
                mae = d
        t_mfe = series[mfe_i][0] - series[idx][0]
        rows.append((bt[:16], sym, bought, pnl, closed, reason or "OPEN",
                     net, rng, pre, wvol, mfe, mae, t_mfe))
        for t in buckets:
            if mfe >= t:
                buckets[t] += 1
    if skipped:
        print("skipped (no ticks):", set(skipped))

    n = len(rows)
    print(f"\n=== MFE reach ({n} trades): % trades whose price hit +X% pre-sell ===")
    for t, c in buckets.items():
        print(f"  +{t:>2}%: {c:4d}  ({c/n*100:.0f}%)")

    print("\nbuy_time        sym        entry      pnl    reason             "
          "net    rng    pre      wvol    MFE    MAE   tMFE")
    for (bt, sym, bought, pnl, closed, reason,
         net, rng, pre, wvol, mfe, mae, t_mfe) in rows:
        def f(x, fmt="%6.1f", na="      -"):
            return (fmt % x) if x is not None else na
        print(f"{bt} {sym:10s} {bought:9.5f} {pnl:+8.2f} {reason[:19]:19s} "
              f"{f(net)} {f(rng)} {f(pre)} {f(wvol,'%8.0f','        -')} "
              f"{f(mfe)} {f(mae)} {t_mfe:5d}s")

    print("\n=== counterfactual flat TP ceiling (MFE>=TP counts as win) ===")
    for tp in (1, 2, 3, 4, 5):
        wins = sum(1 for r in rows if r[10] >= tp)
        pnl_ = wins * tp - (n - wins) * 3
        print(f"  TP {tp}%: {wins} reached, approx net {pnl_:+.1f}%")


if __name__ == "__main__":
    main()
