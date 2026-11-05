#!/usr/bin/env python3
"""Per-day breakdown of the window study (N=36, 90, 180)."""
import heapq
import os
from datetime import datetime, timezone

from pump_window_study import load_data, window_events, simulate_exit

DATA_DIR = os.path.join(os.path.dirname(__file__), "snapshot_data_live")
SLOTS = 5
COOLOFF = 900


def coupled(events, data):
    open_until = []
    open_syms = {}
    cool = {}
    taken = wins = 0
    tot = 0.0
    per_day = {}
    for t, sym, i, rng, net, pre, wvol in events:
        if t < cool.get(sym, 0):
            continue
        while open_until and open_until[0] <= t:
            heapq.heappop(open_until)
        open_syms = {s: e for s, e in open_syms.items() if e > t}
        if len(open_until) >= SLOTS or sym in open_syms:
            continue
        r, j = simulate_exit(data[sym][1], data[sym][0], i)
        ex_t = data[sym][0][j]
        heapq.heappush(open_until, ex_t)
        open_syms[sym] = ex_t
        cool[sym] = ex_t + COOLOFF
        tot += r * 100
        taken += 1
        wins += r > 0
        d = t // 86400
        dd = per_day.setdefault(d, [0, 0.0])
        dd[0] += 1
        dd[1] += r * 100
    return taken, wins, tot, per_day


def main():
    data = load_data()
    for n in (36, 90, 180):
        events = []
        for sym, (ts, ps, vs, cs) in data.items():
            for i, rng, net, pre, wvol in window_events(ts, ps, vs, cs, n):
                events.append((ts[i], sym, i, rng, net, pre, wvol))
        events.sort()
        taken, wins, tot, per_day = coupled(events, data)
        print(f"\nN={n}: taken={taken} wr={wins/taken*100:.0f}% net={tot:+.1f}%")
        for d, (c, v) in sorted(per_day.items()):
            day = datetime.fromtimestamp(d * 86400, timezone.utc)
            print(f"  {day:%m-%d}: {c:3d} trades {v:+8.1f}%")


if __name__ == "__main__":
    main()
