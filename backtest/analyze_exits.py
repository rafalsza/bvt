#!/usr/bin/env python3
"""Post-entry excursion analysis on recorded snapshots.

For every closed trade since CUTOFF, scan the symbol's price series between
buy_time and sell_time and compute:
  MFE  = max favorable excursion (best % above entry while open)
  MAE  = max adverse excursion (worst % below entry while open)
Then simulate alternative exit rules:
  - arm trailing earlier (TTP at +X% instead of +5%)
  - breakeven stop after +Y%
  - hard TP cap
"""
import csv
import gzip
import os
import sqlite3
import sys
from datetime import datetime, timedelta

USER_DATA = sys.argv[1] if len(sys.argv) > 1 else "user_data"
CUTOFF = "2026-10-20 09:00"
SL = -3.0          # base stop
FEE = 0.2          # round-trip fee % already inside profit_dollars approx


def load_trades():
    con = sqlite3.connect(os.path.join(USER_DATA, "transactions.db"))
    rows = con.execute(
        "SELECT symbol, buy_time, sell_time, bought_at, sold_at, profit_dollars, volume "
        "FROM transactions WHERE closed=1 AND buy_time >= ? ORDER BY buy_time",
        (CUTOFF,),
    ).fetchall()
    con.close()
    return rows


def load_prices(symbols, start_day, end_day):
    prices = {s: [] for s in symbols}
    day = start_day
    while day <= end_day:
        p = os.path.join(USER_DATA, "snapshots", f"snapshots_{day}.csv.gz")
        if os.path.exists(p):
            with gzip.open(p, "rt") as f:
                for row in csv.reader(f):
                    if len(row) < 3 or row[0] == "ts":
                        continue
                    if row[1] in prices:
                        prices[row[1]].append((row[0].replace("T", " ")[:19], float(row[2])))
        day = (datetime.strptime(day, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
    for s in prices:
        prices[s].sort()
    return prices


def main():
    trades = load_trades()
    symbols = sorted({t[0] for t in trades})
    days = sorted({t[1][:10].replace("-", "") for t in trades} | {t[2][:10].replace("-", "") for t in trades})
    prices = load_prices(symbols, days[0], days[-1])

    recs = []
    print("%-10s %8s %8s | entry->exit | %7s %7s | %7s" % ("sym", "buy", "sell", "MFE%", "MAE%", "pnl$"))
    for sym, bt, st, bat, sat, pnl, vol in trades:
        ser = prices.get(sym, [])
        mfe, mae = 0.0, 0.0
        for t, p in ser:
            if t <= bt[:19] or (st and t > st[:19]):
                continue
            r = (p - bat) / bat * 100
            mfe = max(mfe, r)
            mae = min(mae, r)
        recs.append(dict(sym=sym, bt=bt, bat=bat, sat=sat, pnl=pnl, mfe=mfe, mae=mae))
        print("%-10s %8s %8s | %.5f->%.5f | %7.2f %7.2f | %7.2f" % (
            sym, bt[11:19], (st or "-")[11:19], bat, sat, mfe, mae, pnl))

    wins = [r for r in recs if r["pnl"] > 0]
    loss = [r for r in recs if r["pnl"] <= 0]
    print(f"\nwins {len(wins)} (+{sum(r['pnl'] for r in wins):.1f})  losses {len(loss)} ({sum(r['pnl'] for r in loss):.1f})")
    print(f"avg MFE: win {sum(r['mfe'] for r in wins)/len(wins):.2f}%  loss {sum(r['mfe'] for r in loss)/len(loss):.2f}%")
    # how many LOSERS reached +X% before dying?
    for thr in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
        n = sum(1 for r in loss if r["mfe"] >= thr)
        print(f"  losers reaching +{thr}% before SL: {n}/{len(loss)}")

    # ---- exit simulations on tick path ----
    print("\n=== EXIT SIMULATIONS (replay ticks buy->sell) ===")
    def simulate(arm_at, trail_dist, hard_tp):
        """arm_at: % above entry that arms trailing; trail_dist: retrace from max;
        hard_tp: instant TP at this %. Returns (net, n)"""
        tot = 0.0
        for r in recs:
            ser = prices.get(r["sym"], [])
            bat = r["bat"]
            armed, peak = False, bat
            exit_p = r["sat"]  # default: actual exit
            got_exit = False
            for t, p in ser:
                if t <= r["bt"][:19]:
                    continue
                if r["bt"][11:19] and r["sat"] and t > r["bt"][:19] and t > (r["bt"][:19],)[0]:
                    pass
                if st and t > st[:19]:
                    break
                if not armed:
                    if (p - bat) / bat * 100 <= SL:
                        exit_p = p
                        got_exit = True
                        break
                    if (p - bat) / bat * 100 >= arm_at:
                        armed = True
                        peak = p
                    if hard_tp and (p - bat) / bat * 100 >= hard_tp:
                        exit_p = p
                        got_exit = True
                        break
                else:
                    peak = max(peak, p)
                    if (p - peak) / peak * 100 <= -trail_dist:
                        exit_p = p
                        got_exit = True
                        break
                    if hard_tp and (p - bat) / bat * 100 >= hard_tp:
                        exit_p = p
                        got_exit = True
                        break
            ret = (exit_p - bat) / bat * 100 - FEE
            tot += ret * 500 / 100  # 500 USDT per position
        return tot

    base = sum(r["pnl"] for r in recs)
    print(f"actual net: {base:.2f}")
    for arm in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 5.0):
        for td in (0.5, 1.0):
            net = simulate(arm, td, None)
            print(f"  arm +{arm}%  trail {td}%   -> net {net:9.2f}")
    for htp in (1.5, 2.0, 3.0):
        net = simulate(5.0, 1.0, htp)  # hard TP only effectively
        print(f"  hard TP +{htp}% (arm 5, trail 1) -> net {net:9.2f}")


if __name__ == "__main__":
    main()
