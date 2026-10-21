#!/usr/bin/env python3
"""Dip-mode exit comparison on recorded ticks.

Entry mirrors live DIP_MODE: window range >= CHG, signed net <= DROP,
last price within NEAR_MIN of window min, and BOUNCE non-decreasing
tail ticks. Exits compared per event:
  - hard TP/SL (current live: TP +1%, SL -4%)
  - trail armed at +ARM, sell on TRAIL retrace from peak (SL still -4%)
"""
import os
import sys
from array import array
from collections import deque
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from replay_snapshots import load_data, FEE, TRADE_USDT, MAX_FORWARD, MAX_HOLD_SEC, N

CHG = 3.0
DROP = -1.5
NEAR_MIN = 0.5
BOUNCE = 2


def dip_events(ts, ps):
    dmax = deque()
    dmin = deque()
    for i in range(len(ps)):
        p = ps[i]
        while dmax and ps[dmax[-1]] <= p:
            dmax.pop()
        dmax.append(i)
        while dmin and ps[dmin[-1]] >= p:
            dmin.pop()
        dmin.append(i)
        if i < N:
            continue
        lo = i - N + 1
        while dmax[0] < lo:
            dmax.popleft()
        while dmin[0] < lo:
            dmin.popleft()
        mx, mn = ps[dmax[0]], ps[dmin[0]]
        rng = (mx - mn) / mn * 100
        if rng < CHG:
            continue
        net = (p - ps[lo]) / ps[lo] * 100
        if net > DROP:
            continue
        if (p - mn) / mn * 100 > NEAR_MIN:
            continue
        if ps[i] <= ps[i - 1] or ps[i - 1] < ps[i - 2]:
            continue
        yield i


def exit_hard(ps, ts, i0, tp, sl):
    e = ps[i0]
    tp_p = e * (1 + tp / 100)
    sl_p = e * (1 - sl / 100)
    t0 = ts[i0]
    for j in range(i0 + 1, min(len(ps), i0 + MAX_FORWARD)):
        p = ps[j]
        if ts[j] - t0 > MAX_HOLD_SEC or p <= sl_p or p >= tp_p:
            return (p / e - 1 - FEE), j
    j = len(ps) - 1
    return (ps[j] / e - 1 - FEE), j


def exit_trail(ps, ts, i0, arm, trail, sl):
    e = ps[i0]
    arm_p = e * (1 + arm / 100)
    sl_p = e * (1 - sl / 100)
    armed = False
    peak = e
    t0 = ts[i0]
    for j in range(i0 + 1, min(len(ps), i0 + MAX_FORWARD)):
        p = ps[j]
        if ts[j] - t0 > MAX_HOLD_SEC:
            return (p / e - 1 - FEE), j
        if not armed:
            if p <= sl_p:
                return (p / e - 1 - FEE), j
            if p >= arm_p:
                armed = True
                peak = p
        else:
            if p > peak:
                peak = p
            if p <= peak * (1 - trail / 100):
                return (p / e - 1 - FEE), j
    j = len(ps) - 1
    return (ps[j] / e - 1 - FEE), j


def main():
    data = load_data()
    print(f"{len(data)} symbols, {sum(len(v[0]) for v in data.values())} ticks")

    events = []  # (epoch, day, sym, idx)
    for sym, (ts, ps) in data.items():
        for i in dip_events(ts, ps):
            events.append((ts[i], ts[i] // 86400, sym, i))
    events.sort()
    print(f"{len(events)} dip events (chg>={CHG} net<={DROP} near-min<{NEAR_MIN} bounce={BOUNCE})")

    exits = [("hardTP1/SL4", ("h", 1.0, 4.0))]
    for arm in (0.8, 1.0, 1.5):
        for tr in (0.3, 0.4, 0.5, 0.75):
            exits.append((f"trail arm{arm}/tr{tr}/SL4", ("t", arm, tr, 4.0)))

    print(f"\n{'exit':22s} {'n':>4s} {'win%':>5s} {'avg%':>6s} {'net$':>8s}  per-day")
    for name, cfg in exits:
        days = {}
        tot = 0.0
        wins = 0
        for t, day, sym, i in events:
            ps, ts = data[sym][1], data[sym][0]
            if cfg[0] == "h":
                r, j = exit_hard(ps, ts, i, cfg[1], cfg[2])
            else:
                r, j = exit_trail(ps, ts, i, cfg[1], cfg[2], cfg[3])
            pct = r * 100
            tot += pct
            wins += pct > 0
            days[day] = days.get(day, 0.0) + pct
        perday = " ".join(
            f"{datetime.utcfromtimestamp(d*86400):%m-%d}:{v*TRADE_USDT/100:+.0f}"
            for d, v in sorted(days.items())
        )
        print(f"{name:22s} {len(events):4d} {wins/len(events)*100:5.1f} "
              f"{tot/len(events):6.3f} {tot*TRADE_USDT/100:8.2f}  {perday}")


if __name__ == "__main__":
    main()
