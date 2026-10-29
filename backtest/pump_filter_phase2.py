#!/usr/bin/env python3
"""Phase-2 coupled sim for promising pump-filter combos.

Realistic constraints: 5 slots, per-symbol mutex, 15min post-exit cooloff,
3 losses/symbol/day buy-block. Reports per-day PnL to check robustness.
"""
import heapq
import os
import pickle
from datetime import datetime, timezone

from pump_filter_study import load_data, simulate_exit

DATA_DIR = os.path.join(os.path.dirname(__file__), "snapshot_data")
EV_CACHE = os.path.join(DATA_DIR, "events_v2.pkl")
TRADE_USDT = 500.0
SLOTS = 5
COOLOFF = 900
TTP = 1.0

# candidate filters: name -> predicate(e)
# e: 0 epoch 1 sym 2 i 3 rng 4 net 5 lvm 6 tsm 7 acc3 8 pre 9 volz 10 chg24
#    11 hour 12 wvol
FILTERS = {
    "A wvol>=5k hrs8-15":
        lambda e: e[12] >= 5000 and 8 <= e[11] < 16,
    "B wvol>=20k hrs8-15":
        lambda e: e[12] >= 20000 and 8 <= e[11] < 16,
    "C wvol>=5k excl chg24[2,5] excl hrs20-23":
        lambda e: e[12] >= 5000 and not (2 <= e[10] < 5) and not (20 <= e[11] < 24),
    "D pre>=2 wvol>=5k hrs8-19":
        lambda e: e[8] >= 2 and e[12] >= 5000 and 8 <= e[11] < 20,
    "E pre>=2 hrs8-19":
        lambda e: e[8] >= 2 and 8 <= e[11] < 20,
    "F wvol>=5k hrs8-19":
        lambda e: e[12] >= 5000 and 8 <= e[11] < 20,
    "G pre>=1 wvol>=5k hrs8-19":
        lambda e: e[8] >= 1 and e[12] >= 5000 and 8 <= e[11] < 20,
    "H baseline (no filter)":
        lambda e: True,
}

EXITS = [(3.0, 5.0, 1.0), (3.0, 2.0, 0.5), (2.0, 2.0, 0.5)]


def coupled(events, data, pred, cfg):
    sl, arm, tr = cfg
    open_until = []
    open_syms = {}
    cool = {}
    losses = {}
    tot = 0.0
    taken = 0
    per_day = {}
    for e in events:
        if not pred(e):
            continue
        t, sym, i = e[0], e[1], e[2]
        day = t // 86400
        if losses.get((sym, day), 0) >= 3:
            continue
        if t < cool.get(sym, 0):
            continue
        while open_until and open_until[0] <= t:
            heapq.heappop(open_until)
        open_syms = {s: x for s, x in open_syms.items() if x > t}
        if len(open_until) >= SLOTS or sym in open_syms:
            continue
        r, j = simulate_exit(data[sym][1], data[sym][0], i, sl, arm, tr, TTP)
        ex_t = data[sym][0][j]
        heapq.heappush(open_until, ex_t)
        open_syms[sym] = ex_t
        cool[sym] = ex_t + COOLOFF
        if r <= 0:
            losses[(sym, day)] = losses.get((sym, day), 0) + 1
        tot += r * 100
        taken += 1
        d = per_day.setdefault(day, [0, 0.0])
        d[0] += 1
        d[1] += r * 100
    return taken, tot, per_day


def main():
    data = load_data()
    with open(EV_CACHE, "rb") as f:
        events, _out = pickle.load(f)
    print(f"{len(events)} events")

    for cfg in EXITS:
        print(f"\n===== exit {cfg} (SL arm trail), slots={SLOTS} =====")
        for name, pred in FILTERS.items():
            taken, tot, per_day = coupled(events, data, pred, cfg)
            days = "  ".join(
                f"{datetime.fromtimestamp(d*86400, timezone.utc).strftime('%m-%d')}:"
                f"{c}tr/{v:+.0f}%"
                for d, (c, v) in sorted(per_day.items()))
            print(f"{name:42s} n={taken:4d} net={tot:8.1f}% ${tot*TRADE_USDT/100:8.0f}"
                  f" | {days}")


if __name__ == "__main__":
    main()
