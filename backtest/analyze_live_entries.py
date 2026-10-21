#!/usr/bin/env python3
"""Replay post-fix live entries against recorded snapshots and test gates.

Reads:
  user_data/transactions.db  -> closed trades (buy_time, sell outcome)
  user_data/snapshots/snapshots_YYYYMMDD.csv.gz -> ts,symbol,price,volume,change_24h

For every closed trade with buy_time >= CUTOFF we reconstruct the detector's
18-sample ring window at buy time and compute features, then compare
winners vs losers and simulate candidate gates.
"""
import csv
import gzip
import os
import sqlite3
import sys
from datetime import datetime, timedelta

USER_DATA = sys.argv[1] if len(sys.argv) > 1 else "/user_data"
CUTOFF = "2026-10-20 09:00"
N_SAMPLES = 18  # TIME_DIFFERENCE x RECHECK_INTERVAL


def load_trades(db_path):
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT symbol, buy_time, bought_at, sold_at, profit_dollars, change_perc "
        "FROM transactions WHERE closed=1 AND buy_time >= ? ORDER BY buy_time",
        (CUTOFF,),
    ).fetchall()
    con.close()
    return rows


def snap_path(day):
    return os.path.join(USER_DATA, "snapshots", f"snapshots_{day}.csv.gz")


def load_prices(symbols, start_day, end_day):
    """symbol -> [(ts, price)] for days covering trades."""
    prices = {s: [] for s in symbols}
    day = start_day
    while day <= end_day:
        p = snap_path(day)
        if os.path.exists(p):
            with gzip.open(p, "rt") as f:
                r = csv.reader(f)
                for row in r:
                    if len(row) < 3 or row[0] == "ts":
                        continue
                    sym = row[1]
                    if sym in prices:
                        prices[sym].append((row[0].replace("T", " ")[:19], float(row[2])))
        day = (datetime.strptime(str(day), "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
    for s in prices:
        prices[s].sort()
    return prices


def feats(sym, buy_time, bought_at, series):
    # ticks strictly before buy_time (detector saw prices up to ~entry)
    bt = buy_time[:19]
    idx = None
    for i in range(len(series) - 1, -1, -1):
        if series[i][0] <= bt:
            idx = i
            break
    if idx is None or idx + 1 < N_SAMPLES:
        return None
    win = series[idx + 1 - N_SAMPLES : idx + 1]
    ps = [p for _, p in win]
    ts = [t for t, _ in win]
    first, last, mn, mx = ps[0], ps[-1], min(ps), max(ps)
    i_max = ps.index(mx)
    net = (last - first) / first * 100
    rng = (mx - mn) / mn * 100
    last_vs_max = (last - mx) / mx * 100
    # ticks since the window high was printed
    ticks_since_max = len(ps) - 1 - i_max
    # consecutive down ticks at the tail
    down_tail = 0
    for j in range(len(ps) - 1, 0, -1):
        if ps[j] < ps[j - 1]:
            down_tail += 1
        else:
            break
    # drawdown inside window before last tick
    peak = ps[0]
    max_dd = 0.0
    for p in ps:
        peak = max(peak, p)
        max_dd = min(max_dd, (p - peak) / peak * 100)
    # longer lookback: price vs 10min and 20min ago
    def price_ago(minutes):
        target = (
            datetime.strptime(bt, "%Y-%m-%d %H:%M:%S") - timedelta(minutes=minutes)
        ).strftime("%Y-%m-%d %H:%M:%S")
        best = None
        for t, p in series[max(0, idx - 400) : idx + 1]:
            if t <= target:
                best = p
            else:
                break
        return best

    p10, p20 = price_ago(10), price_ago(20)
    ret10 = (last - p10) / p10 * 100 if p10 else None
    ret20 = (last - p20) / p20 * 100 if p20 else None
    entry_gap = (bought_at - last) / last * 100 if last else 0.0
    return dict(
        net=net, rng=rng, lvm=last_vs_max, tsm=ticks_since_max, dt=down_tail,
        dd=max_dd, ret10=ret10, ret20=ret20, gap=entry_gap, n_win=len(ps),
        wfirst=ts[0][11:19], wlast=ts[-1][11:19],
    )


def main():
    trades = load_trades(os.path.join(USER_DATA, "transactions.db"))
    print(f"{len(trades)} closed trades since {CUTOFF}")
    symbols = sorted({t[0] for t in trades})
    days = sorted({t[1][:10].replace("-", "") for t in trades})
    start = (datetime.strptime(days[0], "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    print(f"loading snapshots {start}..{days[-1]} for {len(symbols)} symbols...")
    prices = load_prices(symbols, start, days[-1])

    rows = []
    for sym, btime, bat, sat, pnl, chg in trades:
        f = feats(sym, btime, bat, prices.get(sym, []))
        if f is None:
            print(f"  {sym:10s} {btime[11:19]} -> NO SNAPSHOT WINDOW")
            continue
        f.update(sym=sym, btime=btime[11:19], pnl=pnl, chg=chg)
        rows.append(f)

    hdr = ("sym", "buy_t", "pnl", "chg%", "net", "rng", "lvMax", "tSinceMx", "dnTail", "inWinDD", "r10m", "r20m", "gap")
    print("\n%-10s %8s %7s %6s %6s %6s %6s %8s %7s %8s %6s %6s %6s" % hdr)
    for r in rows:
        print("%-10s %8s %7.2f %6.2f %6.2f %6.2f %6.2f %8d %7d %8.2f %6s %6s %6.2f" % (
            r["sym"], r["btime"], r["pnl"], r["chg"], r["net"], r["rng"], r["lvm"],
            r["tsm"], r["dt"], r["dd"],
            f"{r['ret10']:.2f}" if r["ret10"] is not None else "  -",
            f"{r['ret20']:.2f}" if r["ret20"] is not None else "  -",
            r["gap"],
        ))

    wins = [r for r in rows if r["pnl"] > 0]
    loss = [r for r in rows if r["pnl"] <= 0]
    print(f"\nwins={len(wins)} (+{sum(r['pnl'] for r in wins):.1f})  losses={len(loss)} ({sum(r['pnl'] for r in loss):.1f})")

    def avg(rs, k):
        vals = [r[k] for r in rs if r[k] is not None]
        return sum(vals) / len(vals) if vals else float("nan")

    for k in ("net", "rng", "lvm", "tsm", "dt", "dd", "ret10", "ret20", "gap"):
        print(f"  avg {k:8s}  win={avg(wins,k):8.2f}   loss={avg(loss,k):8.2f}")

    # gate simulation: try single-feature cuts, report kept pnl
    print("\n=== GATE SIMULATION (reject trade if feature outside bound) ===")
    def sim(name, pred):
        kept = [r for r in rows if pred(r)]
        drop = [r for r in rows if not pred(r)]
        kp = sum(r["pnl"] for r in kept)
        dp = sum(r["pnl"] for r in drop)
        print(f"{name:42s} keep {len(kept):2d} net {kp:8.2f} | drop {len(drop):2d} net {dp:8.2f}")

    for thr in (-0.3, -0.5, -1.0, -1.5):
        sim(f"last_vs_max >= {thr}", lambda r, t=thr: r["lvm"] >= t)
    for thr in (0, 1, 2, 3):
        sim(f"ticks_since_max <= {thr}", lambda r, t=thr: r["tsm"] <= t)
    for thr in (0, 1, 2, 3):
        sim(f"down_tail <= {thr}", lambda r, t=thr: r["dt"] <= t)
    for thr in (-0.5, -1.0, -2.0, -3.0):
        sim(f"in_window_drawdown >= {thr}", lambda r, t=thr: r["dd"] >= t)
    for thr in (1.0, 1.5, 2.0, 2.5):
        sim(f"net >= {thr}", lambda r, t=thr: r["net"] >= t)
    for thr in (0, -2, -4, -6):
        sim(f"ret10 >= {thr}", lambda r, t=thr: r["ret10"] is not None and r["ret10"] >= t)
    for thr in (0, -2, -4, -6):
        sim(f"ret20 >= {thr}", lambda r, t=thr: r["ret20"] is not None and r["ret20"] >= t)
    # combos
    sim("lvm>=-0.5 AND tsm<=2", lambda r: r["lvm"] >= -0.5 and r["tsm"] <= 2)
    sim("lvm>=-0.5 AND dt<=1", lambda r: r["lvm"] >= -0.5 and r["dt"] <= 1)
    sim("lvm>=-0.3 AND dd>=-1.5", lambda r: r["lvm"] >= -0.3 and r["dd"] >= -1.5)
    sim("net>=2.0 AND lvm>=-0.5", lambda r: r["net"] >= 2.0 and r["lvm"] >= -0.5)
    sim("ret10>=-2 AND lvm>=-0.5", lambda r: (r["ret10"] or -99) >= -2 and r["lvm"] >= -0.5)


if __name__ == "__main__":
    main()
