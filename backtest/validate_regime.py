#!/usr/bin/env python3
"""Validate a 'pump regime' gate on recorded snapshots.

Regime measure: a signal event counts as SUCCESS if price reaches +3%
before -1.5% within 60 min of detection. Flag(t) = number of successes
in the trailing LOOKBACK_H hours across the whole universe.

Test: re-run the coupled simulation (slots/cooloffs/loss limits, current
live entry gates + exits) but only take trades while flag >= K.
"""
import os
import pickle
import heapq
from array import array
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "snapshot_data")
CACHE = os.path.join(DATA_DIR, "parsed.pkl")

N = 18
FEE = 0.002
TRADE_USDT = 500.0
MAX_HOLD_SEC = 8 * 3600
SUCCESS_UP = 3.0      # % above detection = success
SUCCESS_DN = -1.5     # % below detection = failure (hit first)
SUCCESS_TTL = 3600    # seconds to resolve


def load_data():
    with open(CACHE, "rb") as f:
        return pickle.load(f)


def window_events(ts, ps):
    from collections import deque
    dmax = deque(); dmin = deque()
    for i in range(len(ps)):
        p = ps[i]
        while dmax and ps[dmax[-1]] <= p: dmax.pop()
        dmax.append(i)
        while dmin and ps[dmin[-1]] >= p: dmin.pop()
        dmin.append(i)
        if i < N: continue
        lo = i - N + 1
        while dmax[0] < lo: dmax.popleft()
        while dmin[0] < lo: dmin.popleft()
        mx, mn = ps[dmax[0]], ps[dmin[0]]
        rng = (mx - mn) / mn * 100
        if rng < 2.0: continue
        net = (p - ps[lo]) / ps[lo] * 100
        if net < 0.5: continue
        yield i, rng, net, (p - mx) / mx * 100, i - dmax[0]


def resolve(ts, ps, i0):
    """success=+1 if +3% before -1.5% within TTL; -1 fail; 0 timeout."""
    e = ps[i0]
    up = e * 1.03; dn = e * 0.985
    t0 = ts[i0]
    for j in range(i0 + 1, len(ps)):
        if ts[j] - t0 > SUCCESS_TTL:
            return 0
        if ps[j] >= up: return 1
        if ps[j] <= dn: return -1
    return 0


def simulate_exit(ts, ps, i0, sl=3.0, arm=5.0, trail=1.0, ttp=1.0):
    e = ps[i0]
    sl_p, arm_p = e*(1-sl/100), e*(1+arm/100)
    ttp_p = e*(1+(arm+ttp)/100)
    armed, peak, t0 = False, e, ts[i0]
    for j in range(i0+1, len(ps)):
        p = ps[j]
        if ts[j]-t0 > MAX_HOLD_SEC:
            return (p/e-1-FEE)*100, j
        if not armed:
            if p <= sl_p: return (p/e-1-FEE)*100, j
            if p >= arm_p:
                armed = True; peak = p
                if p >= ttp_p: return (p/e-1-FEE)*100, j
        else:
            if p > peak: peak = p
            if p <= peak*(1-trail/100): return (p/e-1-FEE)*100, j
            if p >= ttp_p: return (p/e-1-FEE)*100, j
    j = len(ps)-1
    return (ps[j]/e-1-FEE)*100, j


def main():
    data = load_data()
    # collect events under CURRENT live gates (chg2.5 net1.0 lvm-1.5)
    events = []
    for sym, (ts, ps) in data.items():
        for i, rng, net, lvm, tsm in window_events(ts, ps):
            if rng >= 2.5 and net >= 1.0 and lvm >= -1.5:
                events.append((ts[i], sym, i))
    events.sort()
    print(f"{len(events)} events passing live gates")

    # resolve success/failure for each event
    successes = []  # sorted epoch list of success times
    res_map = {}
    for t, sym, i in events:
        r = resolve(data[sym][0], data[sym][1], i)
        res_map[(t, sym)] = r
        if r == 1:
            successes.append(t)
    successes.sort()
    print(f"successful pumps (+3% before -1.5%): {len(successes)}")

    # per-day success counts
    days = {}
    for t in successes:
        days[datetime.utcfromtimestamp(t).date()] = days.get(datetime.utcfromtimestamp(t).date(), 0) + 1
    print("successes per day:", days)

    import bisect
    def regime_flag(t, lookback_h):
        lo = t - lookback_h * 3600
        return len(successes) - 0 - (len(successes) - (bisect.bisect_left(successes, t) - bisect.bisect_left(successes, lo)))

    def sim(lookback_h, K):
        SLOTS, COOLOFF = 10, 900
        open_until, open_syms, cool, losses = [], {}, {}, {}
        tot, taken, skipped = 0.0, 0, 0
        per_day = {}
        for t, sym, i in events:
            cnt = bisect.bisect_left(successes, t) - bisect.bisect_left(successes, t - lookback_h*3600)
            if cnt < K:
                skipped += 1
                continue
            day = t // 86400
            if losses.get((sym, day), 0) >= 3 or t < cool.get(sym, 0):
                continue
            while open_until and open_until[0] <= t: heapq.heappop(open_until)
            open_syms = {s: e for s, e in open_syms.items() if e > t}
            if len(open_until) >= SLOTS or sym in open_syms:
                continue
            r, j = simulate_exit(data[sym][0], data[sym][1], i)
            ex = data[sym][0][j]
            heapq.heappush(open_until, ex)
            open_syms[sym] = ex
            cool[sym] = ex + COOLOFF
            if r <= 0:
                losses[(sym, day)] = losses.get((sym, day), 0) + 1
            tot += r; taken += 1
            d = datetime.utcfromtimestamp(t).date()
            per_day[d] = per_day.get(d, 0) + r
        return taken, skipped, tot, per_day

    print("\n=== regime-gated sim (live cfg 2.5/1.0/-1.5, SL3 arm5 tr1) ===")
    print("lookback  K | taken skipped | net%   net$   | per-day")
    for lb in (1, 2, 3, 6):
        for K in (1, 2, 3, 5, 8):
            taken, skipped, tot, pd = sim(lb, K)
            pds = " ".join(f"{d}:{v:+.0f}" for d, v in sorted(pd.items()))
            print(f"  {lb}h    {K} | {taken:4d} {skipped:6d} | {tot:7.2f} {tot*5:8.2f} | {pds}")
    # baseline no regime gate
    taken, skipped, tot, pd = sim(1, 0)
    print(f"  OFF     | {taken:4d} {skipped:6d} | {tot:7.2f} {tot*5:8.2f} | " +
          " ".join(f"{d}:{v:+.0f}" for d, v in sorted(pd.items())))


if __name__ == "__main__":
    main()
