#!/usr/bin/env python3
"""Entry-quality autopsy for live trades.

For every transaction: locate the buy tick in that day's snapshot file,
then walk forward ticks to compute MFE (max favorable excursion %),
MAE, time-to-MFE, and the 3-min window context at entry (net, range,
pretrend, window volume). Answers: does the +5% trailing arm ever get
reached, and what TP profile would have captured the winners?

Run inside the bot container: snapshots + transactions.db are mounted.
"""
import csv
import glob
import gzip
import sqlite3
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime

N = 18
DB = "/user_data/transactions.db"
SNAP_GLOB = "/user_data/snapshots/snapshots_*.csv.gz"


def load_ticks():
    """sym -> [(ts_str, epoch, price, vol)] sorted by ts."""
    data = defaultdict(list)
    for fn in sorted(glob.glob(SNAP_GLOB)):
        with gzip.open(fn, "rt") as f:
            for r in csv.reader(f):
                if len(r) < 5 or r[0] == "ts":
                    continue
                try:
                    ep = int(
                        datetime.strptime(r[0][:19], "%Y-%m-%dT%H:%M:%S").timestamp()
                    )
                except ValueError:
                    continue
                data[r[1]].append((r[0], ep, float(r[2]), float(r[3] or 0)))
    for s in data:
        data[s].sort(key=lambda x: x[1])
    return data


def parse_buy_time(t):
    return int(datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S").timestamp())


def main():
    conn = sqlite3.connect(DB)
    trades = conn.execute(
        "select symbol, buy_time, bought_at, sell_time, sold_at, "
        "profit_dollars, sell_reason, closed from transactions "
        "order by buy_time"
    ).fetchall()
    print(f"{len(trades)} trades")
    ticks = load_ticks()

    buckets = {t: 0 for t in (1, 2, 3, 4, 5, 6, 8, 10, 15, 20)}
    rows_out = []
    for sym, bt, bought, st, sold, pnl, reason, closed in trades:
        series = ticks.get(sym)
        if not series:
            continue
        bep = parse_buy_time(bt)
        idx = bisect_left([x[1] for x in series], bep)
        if idx >= len(series):
            continue
        # entry context: last N ticks window ending at entry
        net = rng = pre = wvol = None
        if idx >= N:
            w = [x[2] for x in series[idx - N + 1: idx + 1]]
            rng = (max(w) - min(w)) / min(w) * 100
            net = (w[-1] - w[0]) / w[0] * 100
            wvol = series[idx][3] - series[idx - N][3]
        if idx >= 2 * N:
            pw = [x[2] for x in series[idx - 2 * N + 1: idx - N + 1]]
            pre = (pw[-1] - pw[0]) / pw[0] * 100
        # forward walk for MFE/MAE (until sell tick or EOF)
        sep = parse_buy_time(st) if (st and closed) else None
        mfe = mae = 0.0
        mfe_i = idx
        for j in range(idx + 1, len(series)):
            if sep is not None and series[j][1] > sep:
                break
            d = (series[j][2] - bought) / bought * 100
            if d > mfe:
                mfe, mfe_i = d, j
            if d < mae:
                mae = d
        t_mfe = series[mfe_i][1] - series[idx][1]
        rows_out.append(
            (bt[:16], sym, bought, pnl, closed, reason or "OPEN",
             net, rng, pre, wvol, mfe, mae, t_mfe)
        )
        for t in buckets:
            if mfe >= t:
                buckets[t] += 1

    n = len(rows_out)
    print(f"\n=== MFE reach (of {n} trades): % of trades whose price hit +X% ===")
    for t, c in buckets.items():
        print(f"  +{t:>2}%: {c:4d}  ({c/n*100:.0f}%)")

    print("\n=== per-trade ===")
    print("buy_time        sym        entry    pnl    reason            "
          "net    rng    pre    wvol     MFE    MAE   tMFE")
    for (bt, sym, bought, pnl, closed, reason,
         net, rng, pre, wvol, mfe, mae, t_mfe) in rows_out:
        def f(x, fmt="%6.1f", na="     -"):
            return (fmt % x) if x is not None else na
        print(f"{bt} {sym:10s} {bought:.5f} {pnl:+7.2f} {reason[:18]:18s} "
              f"{f(net)} {f(rng)} {f(pre)} {f(wvol,'%8.0f','       -')} "
              f"{f(mfe)} {f(mae)} {t_mfe:5d}s")

    # what flat TP (with SL3) would have netted, using MFE>=TP as win proxy
    print("\n=== counterfactual flat TP (win if MFE>=TP before SL) ===")
    for tp in (1, 2, 3, 4, 5):
        # crude: count trades with MFE>=tp as +tp, rest -3% (approximation;
        # ignores order of hits, but shows the reach ceiling)
        wins = sum(1 for r in rows_out if r[10] >= tp)
        pnl = wins * tp - (n - wins) * 3
        print(f"  TP {tp}%: {wins} wins, approx net {pnl:+.1f}%")


if __name__ == "__main__":
    main()
